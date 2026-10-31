/** Fonte de dados de exemplo; troque por chamadas reais (fetch, Preferences, SQLite...). */
export interface GreetingRepository {
  load(): Promise<string>
}

export const greetingRepository: GreetingRepository = {
  async load() {
    return 'Olá, Capacitor!'
  },
}
