# MyHOME Home Assistant Integration

Integrazione custom per collegare gateway BTicino/Legrand MyHOME a Home Assistant tramite OpenWebNet.

## Stato del progetto

Questa repository mantiene e sviluppa una versione forkata dell'integrazione MyHOME con focus su:

- stabilita dei worker gateway
- discovery attiva e discovery by activation
- pannello web per discovery e configurazione dispositivi
- miglior supporto climate e power

## Funzionalita principali

- setup gateway tramite Config Flow
- gestione entita: light, cover, climate, sensor, switch, binary_sensor
- servizi custom MyHOME (sync, send_message, discovery)
- configurazione dispositivi dal pannello web (senza dipendenza da `myhome.yml`)
- discovery attiva e import diretto in configurazione
- inserimento e rimozione manuale dispositivi da UI
- supporto discovery power (WHO 18)

## Requisiti

- Home Assistant
- accesso IP al gateway MyHOME nella stessa rete

## Installazione

### Via HACS

1. Aggiungi questa repository come custom repository (categoria `Integration`).
2. Installa `MyHOME` da HACS.
3. Riavvia Home Assistant.

### Manuale

1. Copia `custom_components/myhome` in `config/custom_components/myhome`.
2. Riavvia Home Assistant.
3. Configura il gateway dalla UI di Home Assistant.

## Configurazione dispositivi

La configurazione dei dispositivi avviene dal pannello web MyHOME:

- `MyHOME Setup` per discovery attiva
- `Discovery by Activation` per raccolta passiva
- `Configurazione Dispositivi` per inserimento manuale, import discovery e rimozione

## Compatibilita legacy YAML

Se esiste un file legacy (es. `myhome.yml`), puo essere usato una sola volta per migrazione iniziale verso lo storage interno dell'integrazione.

Esempio legacy disponibile in:

- `examples/myhome.yml`

## Troubleshooting rapido

- Se non arrivano stati dopo un aggiornamento, riavvia Home Assistant.
- Se la discovery fallisce, controlla i log di `custom_components.myhome`.
- Verifica che il gateway sia raggiungibile e credenziali corrette.

## Fork e crediti

Questo progetto e stato avviato come fork dell'ottimo lavoro originale di `anotherjulien`:

- https://github.com/anotherjulien/MyHOME

Grazie a tutti i contributori del progetto originale e a chi contribuisce a questa evoluzione.

## Licenza

Distribuito sotto licenza presente nel file `LICENSE`.
