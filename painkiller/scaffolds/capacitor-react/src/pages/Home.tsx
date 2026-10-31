import { IonContent, IonHeader, IonPage, IonSpinner, IonText, IonTitle, IonToolbar } from '@ionic/react'
import { useGreeting } from './useGreeting'

export default function Home() {
  const greeting = useGreeting()

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar>
          <IonTitle>My App</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent className="ion-padding">
        {greeting.status === 'loading' && <IonSpinner aria-label="Carregando" />}
        {greeting.status === 'ready' && <h1>{greeting.message}</h1>}
        {greeting.status === 'error' && (
          <IonText color="danger">
            <p>Não foi possível carregar.</p>
          </IonText>
        )}
      </IonContent>
    </IonPage>
  )
}
