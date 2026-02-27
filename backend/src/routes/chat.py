import re
import json
import requests
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Depends,
    UploadFile,
    File,
    Form,
    Request,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from src.services.chat_service import chat_session_manager
from src.services.transalation_service import (
    translation_service,
    translation_fallback_service,
)
from src.services.llm_service import llm_service
from src.services.audio_service import audio_service
from src.services.tts_service import tts_service
from src.auth.auth_utils import get_current_user
from src.flows import diagnosis_flow, recommend_crops_flow
import tempfile
import os


def clean_text_for_tts(text: str) -> str:
    """
    Clean text for Text-to-Speech by removing formatting characters
    that should not be spoken aloud.
    """
    if not text:
        return text

    # Remove markdown formatting
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # Remove **bold**
    text = re.sub(r"\*(.*?)\*", r"\1", text)  # Remove *italic*
    text = re.sub(r"__(.*?)__", r"\1", text)  # Remove __underline__
    text = re.sub(r"_(.*?)_", r"\1", text)  # Remove _italic_

    # Remove other formatting characters
    text = re.sub(r"`(.*?)`", r"\1", text)  # Remove `code`
    text = re.sub(r"~~(.*?)~~", r"\1", text)  # Remove ~~strikethrough~~
    text = re.sub(r"#+\s*", "", text)  # Remove markdown headers
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)  # Remove [link](url) -> link

    # Remove extra asterisks and formatting
    text = re.sub(r"\*+", "", text)  # Remove standalone asterisks
    text = re.sub(r"_+", "", text)  # Remove standalone underscores
    text = re.sub(r"`+", "", text)  # Remove standalone backticks

    # Clean up extra whitespace
    text = re.sub(r"\s+", " ", text)  # Replace multiple spaces with single space
    text = text.strip()  # Remove leading/trailing whitespace

    return text


def _sse(event: str, data: dict) -> bytes:
    """Format a Server-Sent Event line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def auto_compact_text(
    text: str, max_sentences: int = 3, max_bullets: int = 5, max_chars: int = 800
) -> str:
    """Compact verbose text to be concise for chat/tts."""
    if not text:
        return text
    text = text.strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    has_bullets = any(ln.lstrip().startswith(("-", "*", "•", "–")) for ln in lines)
    if has_bullets:
        intro = None
        bullets = []
        for ln in lines:
            if not ln.strip():
                continue
            if ln.lstrip().startswith(("-", "*", "•", "–")):
                bullets.append(ln)
            elif intro is None:
                intro = ln
        compact_lines = []
        if intro:
            compact_lines.append(intro)
        if bullets:
            compact_lines.extend(bullets[:max_bullets])
        compact = "\n".join(compact_lines).strip()
    else:
        # Keep first few sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)
        compact = " ".join(sentences[:max_sentences]).strip()
    if len(compact) > max_chars:
        compact = compact[:max_chars].rsplit(" ", 1)[0] + "…"
    return compact


def reverse_geocode(lat: float, lon: float) -> dict:
    """
    Takes latitude and longitude and returns the location info using Photon API.
    """
    try:
        url = "https://photon.komoot.io/reverse"
        params = {"lat": lat, "lon": lon}

        response = requests.get(url, params=params)
        response.raise_for_status()  # Throws error if status code is not 200

        data = response.json()

        if data["features"]:
            return data["features"][0]["properties"]
        else:
            return {"error": "No location found for given coordinates."}
    except Exception as e:
        return {"error": f"Failed to get location: {str(e)}"}


def clean_location_for_display(location: str) -> str:
    """
    Clean location string to remove GPS coordinates and return only the location name.
    """
    if not location:
        return "Unknown location"

    # Check if location contains coordinates (numbers with decimals)
    import re

    coord_pattern = r"([\d.-]+),\s*([\d.-]+)"
    match = re.search(coord_pattern, location)

    if match:
        try:
            lat = float(match.group(1))
            lon = float(match.group(2))

            # Get location name from coordinates
            location_info = reverse_geocode(lat, lon)

            if "error" not in location_info:
                # Build a readable location string
                location_parts = []

                if location_info.get("city"):
                    location_parts.append(location_info["city"])
                elif location_info.get("name"):
                    location_parts.append(location_info["name"])

                if location_info.get("district"):
                    location_parts.append(location_info["district"])

                if location_info.get("country"):
                    location_parts.append(location_info["country"])

                if location_parts:
                    return ", ".join(location_parts)
                else:
                    return "Unknown location"
            else:
                # Fallback: remove coordinates and clean up
                location = re.sub(r",?\s*lat:\s*[\d.-]+", "", location)
                location = re.sub(r",?\s*lon:\s*[\d.-]+", "", location)
                location = re.sub(r"\s*\([\d.-]+,\s*[\d.-]+\)", "", location)
                location = re.sub(r"\s*[\d.-]+,\s*[\d.-]+", "", location)

                # Clean up any remaining artifacts
                location = re.sub(r"\s+", " ", location)
                location = location.strip()
                location = re.sub(r"^,\s*", "", location)
                location = re.sub(r",\s*$", "", location)

                return location if location else "Unknown location"
        except (ValueError, Exception):
            # If coordinate parsing fails, just clean up the string
            location = re.sub(r",?\s*lat:\s*[\d.-]+", "", location)
            location = re.sub(r",?\s*lon:\s*[\d.-]+", "", location)
            location = re.sub(r"\s*\([\d.-]+,\s*[\d.-]+\)", "", location)
            location = re.sub(r"\s*[\d.-]+,\s*[\d.-]+", "", location)

            location = re.sub(r"\s+", " ", location)
            location = location.strip()
            location = re.sub(r"^,\s*", "", location)
            location = re.sub(r",\s*$", "", location)

            return location if location else "Unknown location"
    else:
        # No coordinates found, return as is
        return location.strip()


def parse_lat_lon_from_location(location: str) -> tuple[float, float] | None:
    """Parse latitude and longitude from a location string like '9.145, 40.489'."""
    if not location:
        return None
    try:
        import re

        m = re.search(r"([+-]?[0-9]*\.?[0-9]+)\s*,\s*([+-]?[0-9]*\.?[0-9]+)", location)
        if not m:
            return None
        lat = float(m.group(1))
        lon = float(m.group(2))
        return (lat, lon)
    except Exception:
        return None


def detect_intent(message_en: str) -> str:
    """Detect user intent using the LLM. Returns one of:
    'crop_recommendation' | 'diagnosis' | 'fertilizer_recommendation' | 'general'.
    Falls back to 'general' if unsure.
    """
    try:
        # Keep prompt small and deterministic
        prompt = (
            "Classify the user's request into one of these intents only: "
            "crop_recommendation, diagnosis, fertilizer_recommendation, general.\n"
            "Rules:\n"
            "- crop_recommendation: asking what to plant, best crops, crop suggestions for location/season.\n"
            "- diagnosis: crop disease/health issues, image-based help, symptoms.\n"
            "- fertilizer_recommendation: fertilizer plan, NPK, dosage, when/how to apply.\n"
            "- general: everything else.\n\n"
            f"User: {message_en}\n\n"
            'Respond with ONLY JSON like {"intent": "crop_recommendation"}.'
        )
        resp = llm_service.send_message(prompt, temperature=0.0, max_output_tokens=24)
        data = resp.get("response", "{}")
        import json, re

        m = re.search(r"\{.*\}", data, re.DOTALL)
        if m:
            data = m.group(0)
        parsed = json.loads(data)
        intent_raw = (parsed.get("intent") or "").strip().lower()
        # Normalize common typos/synonyms
        normalized = intent_raw.replace(" ", "_").replace("-", "_")
        if normalized in (
            "croprecommendation",
            "croprecommendatino",
            "crop_recommendation",
        ):
            normalized = "crop_recommendation"
        elif normalized in ("fertilizer", "fertiliser", "fertilizer_recommendation"):
            normalized = "fertilizer_recommendation"
        if normalized in {
            "crop_recommendation",
            "diagnosis",
            "fertilizer_recommendation",
            "general",
        }:
            return normalized
        # Fallback heuristic
        mlc = (message_en or "").lower()
        if (
            ("recommend" in mlc and ("crop" in mlc or "plant" in mlc))
            or ("what to plant" in mlc)
            or ("best crop" in mlc)
        ):
            return "crop_recommendation"
        if any(
            k in mlc
            for k in [
                "disease",
                "blight",
                "symptom",
                "leaf spot",
                "diagnos",
                "unhealthy",
            ]
        ):
            return "diagnosis"
        if any(
            k in mlc for k in ["fertilizer", "fertiliser", "npk", "dosage", "apply"]
        ):
            return "fertilizer_recommendation"
        return "general"
    except Exception:
        return "general"


router = APIRouter(prefix="/api/chat", tags=["Chat"])


class StartSessionRequest(BaseModel):
    user_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    session_id: str
    message: str


class SendAudioMessageRequest(BaseModel):
    session_id: str


@router.post("/start-session")
def start_session(req: StartSessionRequest, current_user=Depends(get_current_user)):
    session = chat_session_manager.start_session(user_id=req.user_id)
    return {"session_id": session.session_id, "created_at": session.created_at}


@router.post("/send-message")
async def send_message(
    request: Request,
    session_id_form: Optional[str] = Form(None),
    message_form: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    preferred_language: Optional[str] = Query(
        None, description="Preferred language for conversation"
    ),
    current_user=Depends(get_current_user),
):
    # Support both JSON body and multipart form
    session_id: Optional[str] = session_id_form
    message: Optional[str] = message_form
    if session_id is None and message is None and image is None:
        try:
            data = await request.json()
        except Exception:
            data = {}
        session_id = data.get("session_id")
        message = data.get("message")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = chat_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Use preferred language if provided, otherwise detect
    if preferred_language:
        user_lang = preferred_language
        print(f"🌍 Using preferred language: {user_lang}")
    else:
        # Detect language using main service, fallback if error
        try:
            user_lang = translation_service.detect_language(message or "")
        except Exception:
            user_lang = translation_fallback_service.detect_language(message or "")
        print(f"🌍 Detected language: {user_lang}")

    message_for_llm = message or ""
    needs_translation = user_lang != "en"
    if needs_translation:
        try:
            message_for_llm = translation_service.translate_to_english(message_for_llm)
        except Exception:
            message_for_llm = translation_fallback_service.translate_to_english(
                message_for_llm
            )

    # Add user message
    if message_for_llm:
        chat_session_manager.add_message(
            session_id, sender="user", message=message_for_llm
        )

    messages_formatted = "\n".join(
        [f"{m.sender}: {m.message}" for m in session.messages[-10:]]
    )

    # Get farmer's personalized information
    farmer_info = f"""
Farmer Profile:
- Name: {current_user.name}
- Location: {clean_location_for_display(current_user.location)}
- Experience: {current_user.years_experience} years
- User Type: {current_user.user_type}
- Main Goal: {current_user.main_goal}
- Preferred Language: {current_user.preferred_language}
- Crops Grown: {current_user.crops_grown}
"""

    # If an image is provided, run the diagnosis flow (function-calling behavior)
    temp_image_path = None
    if image is not None:
        if not image.content_type or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        try:
            suffix = os.path.splitext(image.filename or "upload.jpg")[1] or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(await image.read())
                temp_image_path = tmp.name
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error saving image: {str(e)}")

        try:
            result = await diagnosis_flow(temp_image_path)
        finally:
            try:
                if temp_image_path and os.path.exists(temp_image_path):
                    os.remove(temp_image_path)
            except Exception:
                pass

        structured = result.get("structured_insight")
        if structured:
            problems = structured.get("identified_problems", []) or []
            overall = structured.get("overall_health") or "Unknown"
            severity = structured.get("severity_level") or "Unknown"
            recs = structured.get("recommended_actions", []) or []

            # Clean items and remove trailing punctuation artifacts
            def _clean_list(items):
                cleaned = []
                for it in items:
                    if not isinstance(it, str):
                        it = str(it)
                    it = it.strip().rstrip(",")
                    if it:
                        cleaned.append(it)
                return cleaned

            problems = _clean_list(problems)[:5]
            recs = _clean_list(recs)[:5]

            # Markdown-formatted, scannable summary
            md_lines = [
                f"**Overall:** {overall}",
                f"**Severity:** {severity}",
            ]
            if problems:
                md_lines.append("\n**Problems**:")
                md_lines.extend([f"- {p}" for p in problems])
            if recs:
                md_lines.append("\n**Next steps**:")
                md_lines.extend([f"- {r}" for r in recs])
            assistant_text = "\n".join(md_lines) or "Diagnosis completed."
        else:
            assistant_text = result.get("insight") or "Diagnosis completed."

        # Translate back to user's preferred language if needed
        try:
            needs_translation = user_lang != "en"
        except NameError:
            needs_translation = False
        if needs_translation and assistant_text:
            try:
                assistant_text = translation_service.translate_from_english(
                    assistant_text, user_lang
                )
            except Exception:
                assistant_text = translation_fallback_service.translate_from_english(
                    assistant_text, user_lang
                )
        chat_session_manager.add_message(
            session_id, sender="llm", message=assistant_text
        )

        raw_results = result.get("raw_results", {})
        kindwise = raw_results.get("kindwise", {})
        diseases = kindwise.get("diseases", [])
        crops = kindwise.get("crops", [])
        similar_images = {
            "diseases": [
                {
                    "name": d.get("name"),
                    "similar_images": d.get("similar_images", [])[:6],
                }
                for d in diseases
                if d.get("similar_images")
            ][:3],
            "crops": [
                {
                    "name": c.get("name"),
                    "similar_images": c.get("similar_images", [])[:6],
                }
                for c in crops
                if c.get("similar_images")
            ][:3],
        }

        return {
            "action": "diagnose_crop",
            "response": assistant_text,
            "structured_insight": structured,
            "similar_images": similar_images,
        }

    # General answer when no image is provided
    # LLM-based intent detection
    intent = detect_intent(message_for_llm or "")
    if intent == "crop_recommendation":
        coords = parse_lat_lon_from_location(current_user.location)
        if not coords:
            # Default to Ethiopia center if unavailable
            coords = (9.145, 40.489)
        lat, lon = coords

        try:
            reco = await recommend_crops_flow(lat, lon, past_days=30, forecast_days=14)
            print("reco", reco)
            assistant_text = (
                reco.get("recommendation")
                or "Here are crop suggestions based on your area."
            )
        except Exception as exc:
            assistant_text = "I couldn't fetch crop recommendations right now. Please try again shortly."

        # Translate back if needed
        if needs_translation and assistant_text:
            try:
                assistant_text = translation_service.translate_from_english(
                    assistant_text, user_lang
                )
            except Exception:
                assistant_text = translation_fallback_service.translate_from_english(
                    assistant_text, user_lang
                )

        print("assi: ", assistant_text)
        chat_session_manager.add_message(
            session_id, sender="llm", message=assistant_text
        )
        return {"response": assistant_text}

    prompt = f"""You are an agricultural assistant helping farmers.
Reply policy:
- Be concise by default.
- If the user asks for diagnosis or mentions disease/symptoms, instruct them briefly to attach or take a clear photo of the affected plant using the camera button in the chat, then wait for the image.
- If the question is vague, ask one brief clarifying question.
- Use simple, direct language suited for farmers.

{farmer_info}

Conversation history:
{messages_formatted}

User message:
{message_for_llm}

Provide a brief, helpful answer tailored to the farmer's context."""

    llm_response = llm_service.send_message(
        prompt, temperature=0.2, max_output_tokens=640
    )
    llm_text = llm_response.get("response") or ""

    chat_session_manager.add_message(session_id, sender="llm", message=llm_text)
    # Translate LLM response back if needed
    if needs_translation and llm_text:
        try:
            llm_text = translation_service.translate_from_english(llm_text, user_lang)
        except Exception:
            llm_text = translation_fallback_service.translate_from_english(
                llm_text, user_lang
            )

    llm_text = auto_compact_text(llm_text)
    return {"response": llm_text}


@router.post("/send-voice-message")
async def send_voice_message(
    req: SendMessageRequest,
    preferred_language: Optional[str] = Query(
        None, description="Preferred language for conversation"
    ),
    current_user=Depends(get_current_user),
):
    """
    Send a message and get both text and audio response
    """
    session = chat_session_manager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Use preferred language if provided, otherwise detect
    if preferred_language:
        user_lang = preferred_language
        print(f"🌍 Using preferred language: {user_lang}")
    else:
        # Detect language using main service, fallback if error
        try:
            user_lang = translation_service.detect_language(req.message)
        except Exception:
            user_lang = translation_fallback_service.detect_language(req.message)
        print(f"🌍 Detected language: {user_lang}")

    message_for_llm = req.message
    needs_translation = user_lang != "en"
    if needs_translation:
        try:
            message_for_llm = translation_service.translate_to_english(req.message)
        except Exception:
            message_for_llm = translation_fallback_service.translate_to_english(
                req.message
            )

    # Add user message
    chat_session_manager.add_message(
        req.session_id, sender="user", message=message_for_llm
    )

    messages_formatted = "\n".join(
        [f"{m.sender}: {m.message}" for m in session.messages[-10:]]
    )

    # Get farmer's personalized information
    farmer_info = f"""
Farmer Profile:
- Name: {current_user.name}
- Location: {clean_location_for_display(current_user.location)}
- Experience: {current_user.years_experience} years
- User Type: {current_user.user_type}
- Main Goal: {current_user.main_goal}
- Preferred Language: {current_user.preferred_language}
- Crops Grown: {current_user.crops_grown}
"""

    prompt = f"""You are an agricultural assistant helping farmers.
Reply policy:
- Be concise by default (1–3 sentences). Avoid small talk and generic disclaimers.
- If the question is vague, ask one brief clarifying question.
- Use simple, direct language suited for farmers.

{farmer_info}

Conversation history:
{messages_formatted}

User message:
{message_for_llm}

Provide a brief, helpful answer tailored to the farmer's context."""

    llm_response = llm_service.send_message(
        prompt, temperature=0.2, max_output_tokens=640
    )
    llm_text = llm_response.get("response") or ""

    chat_session_manager.add_message(req.session_id, sender="llm", message=llm_text)

    # Translate LLM response back if needed
    if needs_translation and llm_text:
        try:
            llm_text = translation_service.translate_from_english(llm_text, user_lang)
        except Exception:
            llm_text = translation_fallback_service.translate_from_english(
                llm_text, user_lang
            )

    # Auto-compact verbosity, then clean text for TTS
    llm_text = auto_compact_text(llm_text)
    cleaned_text = clean_text_for_tts(llm_text)

    # Convert text to speech
    tts_result = tts_service.text_to_speech(cleaned_text, user_lang)

    return {
        "response": llm_text,
        "audio_base64": tts_result.get("audio_base64"),
        "audio_format": tts_result.get("audio_format"),
        "language": user_lang,
        "tts_success": tts_result.get("success", False),
    }


@router.post("/send-audio-message")
async def send_audio_message(
    session_id: str,
    audio_file: UploadFile = File(...),
    language: Optional[str] = Query(
        None, description="Language code (en, am, no, sw, es, id)"
    ),
    current_user=Depends(get_current_user),
):
    """
    Send audio message and get LLM response
    """
    # Validate file type
    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="File must be an audio file")

    # Read audio content
    try:
        audio_content = await audio_file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error reading audio file: {str(e)}"
        )

    # Get chat session
    session = chat_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Process audio to text with specified language or auto-detect
    if language:
        # Use the specified language for speech recognition
        print(f"🎤 Using specified language: {language}")
        audio_result = audio_service.process_audio_message_with_language(
            audio_content, language
        )
    else:
        # Auto-detect language
        print(f"🎤 Auto-detecting language")
        audio_result = audio_service.process_audio_message(audio_content)

    if not audio_result["success"]:
        raise HTTPException(
            status_code=400,
            detail=f"Audio processing failed: {audio_result.get('error', 'Unknown error')}",
        )

    transcribed_text = audio_result["text"]
    detected_language = audio_result["detected_language"]
    confidence = audio_result["confidence"]

    # If confidence is too low, return error (lowered threshold for farmers)
    if confidence < 0.2:
        raise HTTPException(
            status_code=400,
            detail=f"Audio quality too low (confidence: {confidence:.2f}). Please speak more clearly.",
        )

    # Use the specified language or detected language
    user_lang = language if language else detected_language
    print(f"🎤 Using language: {user_lang}")

    message_for_llm = transcribed_text
    needs_translation = user_lang != "en"

    if needs_translation:
        try:
            message_for_llm = translation_service.translate_to_english(transcribed_text)
        except Exception:
            message_for_llm = translation_fallback_service.translate_to_english(
                transcribed_text
            )

    # Add user message to chat session
    chat_session_manager.add_message(session_id, sender="user", message=message_for_llm)

    # Format conversation history
    messages_formatted = "\n".join(
        [f"{m.sender}: {m.message}" for m in session.messages[-10:]]
    )

    # Get farmer's personalized information
    farmer_info = f"""
Farmer Profile:
- Name: {current_user.name}
- Location: {clean_location_for_display(current_user.location)}
- Experience: {current_user.years_experience} years
- User Type: {current_user.user_type}
- Main Goal: {current_user.main_goal}
- Preferred Language: {current_user.preferred_language}
- Crops Grown: {current_user.crops_grown}
"""

    # Use the same prompt as text messages
    prompt = f"""You are an agricultural assistant helping farmers.
Reply policy:
- Be concise by default.
- If the user asks for diagnosis or mentions disease/symptoms, instruct them briefly to attach or take a clear photo of the affected plant using the camera button in the chat, then wait for the image.
- If the question is vague, ask one brief clarifying question.
- Use simple, direct language suited for farmers.You are an agricultural assistant helping farmers.
Reply policy:

{farmer_info}

Conversation history:
{messages_formatted}

User message:
{message_for_llm}

Provide a brief, helpful answer tailored to the farmer's context."""

    # Get LLM response
    llm_response = llm_service.send_message(
        prompt, temperature=0.2, max_output_tokens=640
    )
    llm_text = llm_response.get("response") or ""

    # Add LLM response to chat session
    chat_session_manager.add_message(session_id, sender="llm", message=llm_text)

    # Translate LLM response back if needed
    if needs_translation and llm_text:
        try:
            llm_text = translation_service.translate_from_english(llm_text, user_lang)
        except Exception:
            llm_text = translation_fallback_service.translate_from_english(
                llm_text, user_lang
            )

    return {
        "response": llm_text,
        "transcribed_text": transcribed_text,
        "detected_language": detected_language,
        "confidence": confidence,
        "original_language": user_lang,
    }


@router.post("/voice-conversation")
async def voice_conversation(
    session_id: str,
    audio_file: UploadFile = File(...),
    language: Optional[str] = Query(
        None, description="Language code (en, am, no, sw, es, id)"
    ),
    stream: Optional[bool] = Query(
        False,
        description="If true, stream SSE events: detected_language, response_text, audio, done",
    ),
    current_user=Depends(get_current_user),
):
    """
    Real-time voice conversation: Speak to AI and get voice response
    """
    # Validate file type
    if not audio_file.content_type or not audio_file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="File must be an audio file")

    # Read audio content
    try:
        audio_content = await audio_file.read()
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error reading audio file: {str(e)}"
        )

    # Get chat session
    session = chat_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Process audio to text with specified language or auto-detect
    if language:
        print(f"🎤 Using specified language: {language}")
        audio_result = audio_service.process_audio_message_with_language(
            audio_content, language
        )
    else:
        print(f"🎤 Auto-detecting language")
        audio_result = audio_service.process_audio_message(audio_content)

    if not audio_result["success"]:
        raise HTTPException(
            status_code=400,
            detail=f"Audio processing failed: {audio_result.get('error', 'Unknown error')}",
        )

    transcribed_text = audio_result["text"]
    detected_language = audio_result["detected_language"]
    confidence = audio_result["confidence"]

    # If confidence is too low, return error
    if confidence < 0.2:
        raise HTTPException(
            status_code=400,
            detail=f"Audio quality too low (confidence: {confidence:.2f}). Please speak more clearly.",
        )

    # Use the specified language or detected language
    user_lang = language if language else detected_language
    print(f"🎤 Using language: {user_lang}")

    # If streaming is requested, send SSE events progressively
    if stream:

        def event_generator():
            try:
                # Initial language/transcript event
                yield _sse(
                    "detected_language",
                    {
                        "detected_language": detected_language,
                        "confidence": confidence,
                        "original_language": user_lang,
                        "transcribed_text": transcribed_text,
                    },
                )

                # Prepare LLM input
                message_for_llm_local = transcribed_text
                needs_translation_local = user_lang != "en"
                if needs_translation_local:
                    try:
                        message_for_llm_local = (
                            translation_service.translate_to_english(transcribed_text)
                        )
                    except Exception:
                        message_for_llm_local = (
                            translation_fallback_service.translate_to_english(
                                transcribed_text
                            )
                        )

                chat_session_manager.add_message(
                    session_id, sender="user", message=message_for_llm_local
                )
                messages_formatted_local = "\n".join(
                    [f"{m.sender}: {m.message}" for m in session.messages[-10:]]
                )
                farmer_info_local = f"""
Farmer Profile:
- Name: {current_user.name}
- Location: {clean_location_for_display(current_user.location)}
- Experience: {current_user.years_experience} years
- User Type: {current_user.user_type}
- Main Goal: {current_user.main_goal}
- Preferred Language: {current_user.preferred_language}
- Crops Grown: {current_user.crops_grown}
"""
                prompt_local = f"""You are an agricultural assistant helping farmers.
Reply policy:
- Be concise by default.
- If the user asks for diagnosis or mentions disease/symptoms, instruct them briefly to attach or take a clear photo of the affected plant using the camera button in the chat, then wait for the image.
- If the question is vague, ask one brief clarifying question.
- Use simple, direct language suited for farmers.

{farmer_info_local}

Conversation history:
{messages_formatted_local}

current user message:
{message_for_llm_local}

Respond as the agricultural assistant, taking into account the farmer's specific profile, location, experience level, and crops. Provide personalized advice that considers their farming context."""

                llm_response_local = llm_service.send_message(
                    prompt_local, temperature=0.2, max_output_tokens=640
                )
                llm_text_local = llm_response_local.get("response") or ""
                chat_session_manager.add_message(
                    session_id, sender="llm", message=llm_text_local
                )

                if needs_translation_local and llm_text_local:
                    try:
                        llm_text_local = translation_service.translate_from_english(
                            llm_text_local, user_lang
                        )
                    except Exception:
                        llm_text_local = (
                            translation_fallback_service.translate_from_english(
                                llm_text_local, user_lang
                            )
                        )

                llm_text_local = auto_compact_text(llm_text_local)
                yield _sse("response_text", {"response": llm_text_local})

                cleaned_text_local = clean_text_for_tts(llm_text_local)
                tts_result_local = tts_service.text_to_speech(
                    cleaned_text_local, user_lang
                )

                yield _sse(
                    "audio",
                    {
                        "audio_base64": tts_result_local.get("audio_base64"),
                        "audio_format": tts_result_local.get("audio_format"),
                        "language": user_lang,
                        "tts_success": tts_result_local.get("success", False),
                    },
                )

                yield _sse("done", {"ok": True})
            except Exception as exc:
                yield _sse("error", {"message": str(exc)})

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Non-streaming path (original behavior)
    message_for_llm = transcribed_text
    needs_translation = user_lang != "en"
    if needs_translation:
        try:
            message_for_llm = translation_service.translate_to_english(transcribed_text)
        except Exception:
            message_for_llm = translation_fallback_service.translate_to_english(
                transcribed_text
            )

    chat_session_manager.add_message(session_id, sender="user", message=message_for_llm)
    messages_formatted = "\n".join(
        [f"{m.sender}: {m.message}" for m in session.messages[-10:]]
    )
    farmer_info = f"""
Farmer Profile:
- Name: {current_user.name}
- Location: {clean_location_for_display(current_user.location)}
- Experience: {current_user.years_experience} years
- User Type: {current_user.user_type}
- Main Goal: {current_user.main_goal}
- Preferred Language: {current_user.preferred_language}
- Crops Grown: {current_user.crops_grown}
"""
    prompt = f"""You are an agricultural assistant helping farmers.
Reply policy:
- Be concise by default.
- If the user asks for diagnosis or mentions disease/symptoms, instruct them briefly to attach or take a clear photo of the affected plant using the camera button in the chat, then wait for the image.
- If the question is vague, ask one brief clarifying question.
- Use simple, direct language suited for farmers.You are an agricultural assistant helping farmers.
Reply policy:

{farmer_info}

Conversation history:
{messages_formatted}

current user message:
{message_for_llm}

Respond as the agricultural assistant, taking into account the farmer's specific profile, location, experience level, and crops. Provide personalized advice that considers their farming context."""
    llm_response = llm_service.send_message(
        prompt, temperature=0.2, max_output_tokens=640
    )
    llm_text = llm_response.get("response") or ""
    chat_session_manager.add_message(session_id, sender="llm", message=llm_text)
    if needs_translation and llm_text:
        try:
            llm_text = translation_service.translate_from_english(llm_text, user_lang)
        except Exception:
            llm_text = translation_fallback_service.translate_from_english(
                llm_text, user_lang
            )
    llm_text = auto_compact_text(llm_text)
    cleaned_text = clean_text_for_tts(llm_text)
    tts_result = tts_service.text_to_speech(cleaned_text, user_lang)
    return {
        "response": llm_text,
        "transcribed_text": transcribed_text,
        "detected_language": detected_language,
        "confidence": confidence,
        "original_language": user_lang,
        "audio_base64": tts_result.get("audio_base64"),
        "audio_format": tts_result.get("audio_format"),
        "tts_success": tts_result.get("success", False),
    }


@router.get("/history")
def get_history(session_id: str = Query(...), current_user=Depends(get_current_user)):
    history = chat_session_manager.get_history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"messages": [m.dict() for m in history]}
