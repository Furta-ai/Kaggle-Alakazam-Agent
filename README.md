# Alakazam Search Agent

Questo repository contiene il codice per un agente competitivo progettato per giocare a un gioco di carte collezionabili (ispirato al GCC Pokémon, nello specifico per l'Hackathon Kaggle). L'agente pilota un mazzo incentrato su Alakazam e gestisce una delle sfide più complesse nell'ambito dell'Intelligenza Artificiale applicata ai giochi: il processo decisionale in un ambiente con informazioni imperfette, un fattore di ramificazione (branching factor) altissimo e una ricompensa sparsa (il risultato si sa solo a fine partita).

## 1. Il Problema

Scrivere un bot per un gioco di carte collezionabili moderno è un incubo algoritmico. A differenza degli scacchi o del Go, qui non vediamo tutto il tabellone. Non conosciamo l'ordine delle carte nel nostro mazzo, non sappiamo cosa nascondono le carte premio e, soprattutto, non vediamo la mano del nostro avversario né la composizione esatta del suo deck. 

A questo si aggiunge un numero enorme di azioni possibili in ogni turno: giocare carte, attivare abilità, assegnare energie, evolvere, ritirare il Pokémon attivo. Moltiplicando tutto per le incognite, l'albero decisionale esplode immediatamente. Una ricerca esaustiva standard (come MCTS o Minimax profondo) è letteralmente fuori discussione. Inoltre, il gioco non ti dà "punti" mentre giochi: sai se hai vinto o perso solo alla fine. Serve quindi un modo per valutare lo stato del gioco a metà partita e capire se stiamo andando bene, in modo da guidare una ricerca più superficiale.

## 2. L'Approccio: Euristiche, Determinizzazione e Rules-Opponent

Per risolvere questi problemi, l'agente (`alak_search_agent.py` e la variante `alak_search_ro.py`) combina diverse tecniche avanzate:

### A. Valutazione tramite Euristiche Ingegnerizzate (Feature Engineering)
Tutto parte da una robusta funzione di valutazione scritta a mano che assegna un punteggio alle varie azioni possibili (`heuristic_scores`). L'agente calcola la pressione sul board, il vantaggio di risorse, la capacità di pescare (stima di `max_hand_inc`), i danni letali (se può chiudere una kill) e la priorità delle carte da giocare.
Ogni singola azione (giocare un Pokémon, usare un Poffin, assegnare un'energia) ha un peso. Questi pesi sono stati finemente calibrati (vedi il dizionario `WEIGHTS`), tenendo conto anche di fasi "early game" o "late game". Ad esempio, giocare un'Abra al turno 1 ha un peso enorme, ma cala drasticamente se abbiamo la panchina già piena o siamo a fine partita.

### B. Determinizzazione
Come gestiamo ciò che non vediamo? Mentiamo all'algoritmo creando dei "mondi possibili". 
Nel codice, l'agente campiona diversi mondi paralleli coerenti con le informazioni pubbliche (la funzione `_sample_hidden`). Conta le carte visibili e riempie le zone nascoste (mazzo, premi, mano avversaria) in modo plausibile. 
Per l'avversario, usa un sistema di "archetipi" (`_match_archetype`). Avendo un database di mazzi competitivi, guarda le carte sul board dell'avversario, riconosce l'archetipo e riempie i buchi della sua mano e del suo mazzo basandosi sulle liste di quel tipo di mazzo.

### C. Ricerca 2-Ply Minimax e Opponent Modeling (Rules-Opponent)
Invece di fidarsi solo dell'euristica a colpo d'occhio, l'agente "guarda avanti" di un paio di mosse usando i mondi campionati. Ma qui introduce una meccanica brillante chiamata **Rules-Opponent (RO)**, implementata in `alak_search_ro.py`:
1. Durante la ricerca (lookahead), simulare le mosse dell'avversario usando la nostra euristica (pensata per Alakazam) porterebbe a stime sbagliatissime, perché l'avversario sta giocando un mazzo completamente diverso.
2. Quindi, la funzione `_detect_opp` rileva "chi" abbiamo davanti basandosi sulle carte visibili (es. se vediamo un Dreepy capisce che affronta Dragapult; se vede Duraludon capisce che affronta Archaludon).
3. A questo punto, instrada le simulazioni del turno avversario delegandole a specifici **sotto-agenti dedicati** (es. `crustle_agent.py`, `dragapult_agent.py`, ecc.).
4. Poiché molti di questi avversari sono bot "rule-based" (deterministici), il nostro agente può prevedere con precisione assoluta le loro mosse e sfruttarne le vulnerabilità. Se l'archetipo è sconosciuto, si affida a un `pool_agent` generalista.

Per ogni azione candidata:
- Simula di fare la mossa completando il turno in modo greedy.
- Cede il turno all'avversario e calcola la risposta esatta dell'avversario interrogando il sotto-agente rilevato.
- Calcola il valore dello stato finale e fa la media su tutte le determinizzazioni.


### E. Gestione dello Stato e Registro Agenti Avversari
Un dettaglio tecnico cruciale dell'architettura RO è la gestione della memoria dei sotto-agenti avversari. Molti di questi bot (come Dragapult o Iono) leggono un file `deck.csv` locale all'avvio per fare *card counting*. Se importati direttamente, leggerebbero il nostro mazzo Alakazam, sballando tutta la loro logica!
Per risolvere questo problema, il sistema usa un registro dedicato (`official_agents.py`). Al momento dell'importazione, questo registro inietta "a forza" la lista esatta del mazzo avversario (es. le 60 carte esatte di Mega Lucario o Dragapult) nelle variabili globali del bot avversario (`my_deck`). In questo modo, quando simuliamo le loro mosse, i bot avversari ragionano con la consapevolezza perfetta del loro vero mazzo.

### D. Valutazione dello Stato Foglia (Leaf Evaluation) e Memetic Tuning
La funzione di valutazione nei nodi foglia della ricerca (`_leaf_eval`) determina quanto sia vantaggioso uno stato dopo aver simulato l'intero turno e le contromosse dell'avversario. Sebbene il codice contenga una flag opzionale per utilizzare un modello XGBoost, la valutazione finale si affida a una **robusta logica puramente euristica** basata sui fondamentali del gioco:
- **Differenza di Carte Premio**: il fattore più influente.
- **Vantaggio in Campo**: la differenza tra i Punti Salute (HP) totali dei nostri Pokémon e quelli dell'avversario.
- **Economia di Energie**: quante energie abbiamo in gioco rispetto all'avversario.
- **Sicurezza del Board**: enormi penalità assegnate se il giocatore non ha un Pokémon in posizione attiva.


---

Questo approccio ibrido ci permette di navigare un ambiente ad informazione imperfetta con grande reattività. Anticipando le mosse esatte dell'avversario grazie al modello Rules-Opponent, l'agente trasforma l'incertezza in un vantaggio tattico devastante.
