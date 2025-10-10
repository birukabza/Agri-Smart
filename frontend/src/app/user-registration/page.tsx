"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { User, Mail, MapPin, Brain, Target, Calendar, ArrowRight, ArrowLeft, Plus, X } from "lucide-react"
import { useRouter } from "next/navigation"
import { useAuth } from "@/contexts/AuthContext"
import { useLanguage } from "@/contexts/LanguageContext"

interface Crop {
  name: string
  icon: string
}

export default function UserRegistrationPage() {
  const [formData, setFormData] = useState({
    user_type: "",
    years_experience: "",
    main_goal: ""
  })
  const [currentlyGrowingCrops, setCurrentlyGrowingCrops] = useState<Crop[]>([])
  const [planningToGrowCrops, setPlanningToGrowCrops] = useState<Crop[]>([])
  const [newCropName, setNewCropName] = useState("")
  const [showAddForm, setShowAddForm] = useState(false)
  const [activeSection, setActiveSection] = useState<"current" | "planned">("current")
  const [errors, setErrors] = useState<Record<string, string>>({})
  const router = useRouter()
  const { completeRegistration, isAuthenticated, isLoading } = useAuth()
  const { t, selectedLanguage } = useLanguage()

  // Redirect authenticated users to main page (only for existing users, not new registrations)
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      // Check if this is a new registration by looking for onboarding data
      const authData = sessionStorage.getItem('auth_data')

      // If we have onboarding data, continue with onboarding flow
      if (authData) {
        // New user with onboarding data - let them continue the flow
        return
      }

      // Existing user - redirect to main page
      router.push("/main-page")
    }
  }, [isAuthenticated, isLoading, router])

  // Debug: Monitor crops state changes
  useEffect(() => {
    console.log('🔄 Currently Growing Crops State Changed:', currentlyGrowingCrops)
  }, [currentlyGrowingCrops])

  useEffect(() => {
    console.log('🔄 Planning to Grow Crops State Changed:', planningToGrowCrops)
  }, [planningToGrowCrops])

  const handleAddCrop = () => {
    if (newCropName.trim()) {
      const newCrop: Crop = {
        name: newCropName.trim(),
        icon: "🌱"
      }

      console.log('🌱 Adding crop:', newCrop, 'to section:', activeSection)

      if (activeSection === "current") {
        const updatedCrops = [...currentlyGrowingCrops, newCrop]
        console.log('🌾 Updated currently growing crops:', updatedCrops)
        setCurrentlyGrowingCrops(updatedCrops)
      } else {
        const updatedCrops = [...planningToGrowCrops, newCrop]
        console.log('🌾 Updated planning to grow crops:', updatedCrops)
        setPlanningToGrowCrops(updatedCrops)
      }

      setNewCropName("")
      setShowAddForm(false)
    }
  }

  const handleRemoveCrop = (cropName: string, section: "current" | "planned") => {
    if (section === "current") {
      setCurrentlyGrowingCrops(currentlyGrowingCrops.filter(crop => crop.name !== cropName))
    } else {
      setPlanningToGrowCrops(planningToGrowCrops.filter(crop => crop.name !== cropName))
    }
  }

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    if (!formData.user_type) {
      newErrors.user_type = t("selectFarmingExperience")
    }

    if (!formData.years_experience) {
      newErrors.years_experience = t("selectYearsExperience")
    }

    if (!formData.main_goal) {
      newErrors.main_goal = t("selectMainGoal")
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async () => {
    if (validateForm()) {
      try {
        // Get all stored data from session storage
        const authData = JSON.parse(sessionStorage.getItem('auth_data') || '{}')
        const locationData = JSON.parse(sessionStorage.getItem('farmer_location') || '{}')

        // Debug: Log crops data
        console.log('🌾 Currently Growing Crops:', currentlyGrowingCrops)
        console.log('🌾 Planning to Grow Crops:', planningToGrowCrops)

        // Prepare user data for backend
        const userData = {
          email: authData.email,
          password: authData.password,
          name: authData.name,
          location: locationData.latitude && locationData.longitude
            ? `${locationData.latitude}, ${locationData.longitude}`
            : "Unknown",
          preferred_language: selectedLanguage,
          user_type: formData.user_type,
          years_experience: parseInt(formData.years_experience) || 1,
          main_goal: formData.main_goal,
          crops_grown: [
            ...currentlyGrowingCrops.map(crop => `${crop.name}:current`),
            ...planningToGrowCrops.map(crop => `${crop.name}:planned`)
          ]
        }

        // console.log('📤 Sending userData to backend:', userData)

        // Send data to backend using AuthContext
        await completeRegistration(userData)

        // Store user data in session storage
        sessionStorage.setItem('user_registration_data', JSON.stringify({
          ...formData,
          preferred_language: selectedLanguage,
          crops_grown: [
            ...currentlyGrowingCrops.map(crop => `${crop.name}:current`),
            ...planningToGrowCrops.map(crop => `${crop.name}:planned`)
          ]
        }))

        // Clear onboarding data since user has completed the full flow
        sessionStorage.removeItem('auth_data')
        sessionStorage.removeItem('farmer_location')

        // Navigate to main app
        router.push("/main-page")
      } catch (error: any) {
        console.error('Registration error:', error)

        // Handle specific error cases
        if (error.message && error.message.includes('Email already registered')) {
          alert('This email is already registered. Please sign in instead or use a different email address.')
          router.push("/auth-options")
        } else {
          alert('Registration failed. Please try again.')
        }
      }
    }
  }

  const handleBack = () => {
    router.push("/language-selection")
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-green-50 to-green-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-20 h-20 bg-green-500 rounded-full flex items-center justify-center mx-auto mb-4">
            <User className="h-10 w-10 text-white" />
          </div>
          <h1 className="text-3xl font-bold text-green-800 mb-2">{t("tellUsAboutFarming")}</h1>
          <p className="text-green-600 text-lg">{t("helpPersonalizeExperience")}</p>
        </div>

        {/* Registration Form */}
        <Card className="rounded-2xl border-2 border-green-100 shadow-lg">
          <CardContent className="p-6 space-y-6">
            {/* User Type */}
            <div className="space-y-2">
              <Label htmlFor="user_type" className="text-green-700 font-medium">
                {t("farmingExperience")}
              </Label>
              <Select
                value={formData.user_type}
                onValueChange={(value) => setFormData({ ...formData, user_type: value })}
              >
                <SelectTrigger className="rounded-xl border-green-200 focus:border-green-500">
                  <SelectValue placeholder={t("farmingExperience")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="aspiring">{t("aspiringFarmer")}</SelectItem>
                  <SelectItem value="beginner">{t("beginnerFarmer")}</SelectItem>
                  <SelectItem value="experienced">{t("experiencedFarmer")}</SelectItem>
                  <SelectItem value="explorer">{t("explorerFarmer")}</SelectItem>
                </SelectContent>
              </Select>
              {errors.user_type && (
                <p className="text-red-600 text-sm">{errors.user_type}</p>
              )}
            </div>

            {/* Years Experience */}
            <div className="space-y-2">
              <Label htmlFor="years_experience" className="text-green-700 font-medium">
                {t("yearsOfExperience")}
              </Label>
              <Select
                value={formData.years_experience}
                onValueChange={(value) => setFormData({ ...formData, years_experience: value })}
              >
                <SelectTrigger className="rounded-xl border-green-200 focus:border-green-500">
                  <SelectValue placeholder={t("selectYearsExperience")} />
                </SelectTrigger>
                <SelectContent>
                  {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25, 30].map((years) => (
                    <SelectItem key={years} value={years.toString()}>
                      {years} {years === 1 ? 'year' : 'years'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.years_experience && (
                <p className="text-red-600 text-sm">{errors.years_experience}</p>
              )}
            </div>

            {/* Main Goal */}
            <div className="space-y-2">
              <Label htmlFor="main_goal" className="text-green-700 font-medium">
                {t("mainGoal")}
              </Label>
              <Select
                value={formData.main_goal}
                onValueChange={(value) => setFormData({ ...formData, main_goal: value })}
              >
                <SelectTrigger className="rounded-xl border-green-200 focus:border-green-500">
                  <SelectValue placeholder={t("mainGoal")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="increase_yield">{t("increaseCropYield")}</SelectItem>
                  <SelectItem value="reduce_costs">{t("reduceFarmingCosts")}</SelectItem>
                  <SelectItem value="sustainable_farming">{t("sustainableFarming")}</SelectItem>
                  <SelectItem value="organic_farming">{t("organicFarming")}</SelectItem>
                  <SelectItem value="market_access">{t("betterMarketAccess")}</SelectItem>
                </SelectContent>
              </Select>
              {errors.main_goal && (
                <p className="text-red-600 text-sm">{errors.main_goal}</p>
              )}
            </div>

            {/* Crop Selection */}
            <div className="space-y-4">
              <h3 className="text-lg font-semibold text-green-800">Your Crops</h3>

              {/* Currently Growing Crops */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-green-700 font-medium">{t("currentlyGrowing")}</Label>
                  <Button
                    onClick={() => {
                      setActiveSection("current")
                      setShowAddForm(true)
                    }}
                    size="sm"
                    variant="outline"
                    className="border-green-200 text-green-600 hover:bg-green-50"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    {t("addCrop")}
                  </Button>
                </div>

                {/* Add Crop Form */}
                {showAddForm && activeSection === "current" && (
                  <div className="space-y-3 p-4 bg-green-50 rounded-xl border border-green-200">
                    <Label className="text-sm font-medium text-green-700">{t("cropName")}</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        value={newCropName}
                        onChange={(e) => setNewCropName(e.target.value)}
                        placeholder={t("enterCropName")}
                        className="flex-1"
                        onKeyPress={(e) => e.key === 'Enter' && handleAddCrop()}
                      />
                      <Button
                        onClick={handleAddCrop}
                        size="sm"
                        className="bg-green-500 hover:bg-green-600"
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}

                {/* Selected Currently Growing Crops */}
                {currentlyGrowingCrops.length > 0 && (
                  <div className="space-y-2">
                    {currentlyGrowingCrops.map((crop, index) => (
                      <div key={index} className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{crop.icon}</span>
                          <span className="font-medium">{crop.name}</span>
                        </div>
                        <Button
                          onClick={() => handleRemoveCrop(crop.name, "current")}
                          size="sm"
                          variant="outline"
                          className="text-red-600 hover:text-red-700"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}

                {currentlyGrowingCrops.length === 0 && (
                  <div className="text-center py-4 text-green-600">
                    <p className="text-sm">{t("noCropsSelected")}</p>
                  </div>
                )}
              </div>

              {/* Planning to Grow Crops */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-blue-700 font-medium">{t("planningToGrow")}</Label>
                  <Button
                    onClick={() => {
                      setActiveSection("planned")
                      setShowAddForm(true)
                    }}
                    size="sm"
                    variant="outline"
                    className="border-blue-200 text-blue-600 hover:bg-blue-50"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    {t("addCrop")}
                  </Button>
                </div>

                {/* Add Crop Form */}
                {showAddForm && activeSection === "planned" && (
                  <div className="space-y-3 p-4 bg-blue-50 rounded-xl border border-blue-200">
                    <Label className="text-sm font-medium text-blue-700">{t("cropName")}</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        value={newCropName}
                        onChange={(e) => setNewCropName(e.target.value)}
                        placeholder={t("enterCropName")}
                        className="flex-1"
                        onKeyPress={(e) => e.key === 'Enter' && handleAddCrop()}
                      />
                      <Button
                        onClick={handleAddCrop}
                        size="sm"
                        className="bg-blue-500 hover:bg-blue-600"
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}

                {/* Selected Planning to Grow Crops */}
                {planningToGrowCrops.length > 0 && (
                  <div className="space-y-2">
                    {planningToGrowCrops.map((crop, index) => (
                      <div key={index} className="flex items-center justify-between p-3 bg-blue-50 rounded-lg border border-blue-200">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{crop.icon}</span>
                          <span className="font-medium">{crop.name}</span>
                        </div>
                        <Button
                          onClick={() => handleRemoveCrop(crop.name, "planned")}
                          size="sm"
                          variant="outline"
                          className="text-red-600 hover:text-red-700"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}

                {planningToGrowCrops.length === 0 && (
                  <div className="text-center py-4 text-blue-600">
                    <p className="text-sm">{t("noCropsSelected")}</p>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Navigation Buttons */}
        <div className="mt-8 flex gap-4">
          <Button
            onClick={handleBack}
            variant="outline"
            className="flex-1 border-green-200 text-green-600 hover:bg-green-50 py-3 rounded-xl"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t("back")}
          </Button>

          <Button
            onClick={handleSubmit}
            className="flex-1 bg-green-500 hover:bg-green-600 text-white font-bold py-3 rounded-xl"
          >
            {t("continueToApp")}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>

        {/* Footer */}
        <div className="mt-6 text-center text-sm text-green-600">
          <p>Your information helps us provide personalized farming advice</p>
        </div>
      </div>
    </div>
  )
} 