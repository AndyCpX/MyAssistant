#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

typedef enum {
    STREAM_OK,        // risposta ricevuta dal servizio
    STREAM_ERROR,     // errore di rete / servizio
    STREAM_ABORTED,   // sessione annullata (es. nessun parlato dopo la wake word)
} stream_status_t;

typedef struct {
    stream_status_t status;
    char label[16];   // positive | neutral | negative (se STREAM_OK)
    float score;
    bool follow_up;   // l'assistente attende una risposta: riaprire l'ascolto senza wake word
    char audio[64];   // percorso dell'audio della risposta (vuoto = nessuno)
} sentiment_result_t;

typedef void (*sentiment_cb_t)(const sentiment_result_t *res);

/** Crea il task di upload. Va chiamata solo se la rete è disponibile. */
esp_err_t streamer_init(sentiment_cb_t cb);

/** Apre una sessione di streaming. false se non inizializzato o già in corso. */
bool streamer_begin(void);

/** Accoda audio PCM16 mono 16 kHz alla sessione (non bloccante; scarta se il buffer è pieno). */
void streamer_push(const int16_t *pcm, size_t samples);

/** Fine enunciato: invia quanto accodato, chiude lo stream e attende il risultato. */
void streamer_finish(void);

/** Annulla la sessione senza attendere un risultato. */
void streamer_abort(void);
