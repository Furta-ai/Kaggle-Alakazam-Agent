# Alakazam Search Agent

Questo repository contiene il codice per un agente competitivo progettato per giocare a un gioco di carte collezionabili (ispirato al GCC Pokémon, nello specifico per l'Hackathon Kaggle). L'agente pilota un mazzo incentrato su Alakazam e gestisce una delle sfide più complesse nell'ambito dell'Intelligenza Artificiale applicata ai giochi: il processo decisionale in un ambiente con informazioni imperfette, un fattore di ramificazione (branching factor) altissimo e una ricompensa sparsa (il risultato si sa solo a fine partita).

## 1. Il Problema

Scrivere un bot per un gioco di carte collezionabili moderno è un incubo algoritmico. A differenza degli scacchi o del Go, qui non vediamo tutto il tabellone. Non conosciamo l'ordine delle carte nel nostro mazzo, non sappiamo cosa nascondono le carte premio e, soprattutto, non vediamo la mano del nostro avversario né la composizione esatta del suo deck. 

A questo si aggiunge un numero enorme di azioni possibili in ogni turno: giocare carte, attivare abilità, assegnare energie, evolvere, ritirare il Pokémon attivo. Moltiplicando tutto per le incognite, l'albero decisionale esplode immediatamente. Una ricerca esaustiva standard (come MCTS o Minimax profondo) è letteralmente fuori discussione. Inoltre, il gioco non ti dà "punti" mentre giochi: sai se hai vinto o perso solo alla fine. Serve quindi un modo per valutare lo stato del gioco a metà partita e capire se stiamo andando bene, in modo da guidare una ricerca più superficiale.

## 2. L'Approccio: Heuristic, Determinizzazione e Ricerca

Per risolvere questi problemi, l'agente (`alak_search_agent.py`) combina diverse tecniche:

### A. Valutazione tramite Euristiche Ingegnerizzate (Feature Engineering)
Tutto parte da una robusta funzione di valutazione scritta a mano che assegna un punteggio alle varie azioni possibili (`heuristic_scores`). L'agente calcola la pressione sul board, il vantaggio di risorse, la capacità di pescare (stima di `max_hand_inc`), i danni letali (se può chiudere una kill) e la priorità delle carte da giocare.
Ogni singola azione (giocare un Pokémon, usare un Poffin, assegnare un'energia) ha un peso. Questi pesi sono stati finemente calibrati (vedi il dizionario `WEIGHTS`), tenendo conto anche di fasi "early game" o "late game". Ad esempio, giocare un'Abra al turno 1 ha un peso enorme, ma cala drasticamente se abbiamo la panchina già piena o siamo a fine partita.

### B. Determinizzazione
Come gestiamo ciò che non vediamo? Mentiamo all'algoritmo creando dei "mondi possibili". 
Nel codice, l'agente campiona diversi mondi paralleli coerenti con le informazioni pubbliche (la funzione `_sample_hidden`). Conta le carte visibili e riempie le zone nascoste (mazzo, premi, mano avversaria) in modo plausibile. 
Per l'avversario, fa qualcosa di ancora più furbo: usa un sistema di "archetipi" (`_match_archetype`). Avendo un database di mazzi competitivi, guarda le carte sul board dell'avversario, riconosce l'archetipo e riempie i buchi della sua mano e del suo mazzo basandosi sulle liste di quel tipo di mazzo.

### C. Ricerca 2-Ply Minimax (Lookahead)
Invece di fidarsi solo dell'euristica a colpo d'occhio, l'agente "guarda avanti" di un paio di mosse usando i mondi campionati.
Per ogni azione candidata (scremata dall'euristica base per non perdere tempo), l'agente:
1. Simula di fare quella mossa e completa il proprio turno in modo "greedy" (scegliendo le azioni successive migliori secondo l'euristica).
2. Passa il turno all'avversario e simula le sue risposte peggiori per noi (Minimax a profondità 2).
3. Calcola il valore dello stato finale (Leaf Evaluation).
4. Media i risultati ottenuti in tutti i mondi campionati (determinizzazioni).
Se questa simulazione rivela che una mossa è nettamente migliore di quella suggerita dall'euristica base, l'agente sovrascrive la scelta (override).

### D. Valutazione dello Stato e Curriculum Learning (Self-Play)
La sfida vera, come detto, è la *funzione di valutazione* nei nodi foglia della ricerca (`_leaf_eval`). 
Inizialmente basata solo su differenze di HP, energie e carte premio, la valutazione è stata poi potenziata usando il Machine Learning. L'agente sfrutta un modello XGBoost (`_learned_pwin`) addestrato su migliaia di partite giocate in *self-play*.
Per evitare che l'agente imparasse a battere solo se stesso o un unico tipo di mazzo, l'addestramento ha seguito un curriculum alternando avversari di livello e stile crescenti (Curriculum Learning). Questo assicura che la policy finale sia generalista, solida e pronta ad affrontare strategie diverse. Infine, i pesi dell'euristica sono stati affinati ulteriormente tramite algoritmi genetici o regressioni (come visibile negli override di "memetic-tuned").

---

Questo approccio ibrido ci permette di navigare un ambiente ad informazione imperfetta con grande reattività, compensando la mancanza di ricerca profonda con una funzione di valutazione estremamente sofisticata e guidata dai dati.
