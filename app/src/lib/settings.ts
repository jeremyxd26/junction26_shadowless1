import { createContext, useContext } from 'react'
import type { Language } from '../api/types.ts'
import { strings } from './i18n.ts'

export interface Settings {
  lang: Language
  customerId: string | null
  t: ReturnType<typeof strings>
}

export const SettingsContext = createContext<Settings>({ lang: 'en', customerId: null, t: strings('en') })

export function useSettings(): Settings {
  return useContext(SettingsContext)
}
