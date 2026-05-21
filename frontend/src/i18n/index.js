import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './en.json'
import zh from './zh.json'
import api from '../lib/api'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    zh: { translation: zh },
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
})

export async function detectLocale() {
  try {
    const res = await api.get('/settings')
    const locale = res.data.settings?.locale || 'en'
    await i18n.changeLanguage(locale)
    return locale
  } catch {
    await i18n.changeLanguage('en')
    return 'en'
  }
}

export default i18n
