import type { InjectionKey } from 'vue'

export type OpenAISettings = () => void

export const openAISettingsKey: InjectionKey<OpenAISettings> = Symbol('open-ai-settings')
