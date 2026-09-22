# =============================================================================
#  alak_search_ro.py - Variante di alak_search con RULES-OPPONENT nel search.
#  -----------------------------------------------------------------------------
#  Nel 2-ply minimax di alak_search, i nodi-AVVERSARIO venivano giocati con
#  l'euristica Alakazam (modello sbagliato). Qui rileviamo l'archetipo avversario
#  dalle carte visibili e, nei rollout, instradiamo le mosse-avversario all'AGENTE
#  DEDICATO (Dragapult/Crustle/Archaludon/...), come fa agent_mcts_mio. Deterministico
#  = un solo figlio. Fallback all'euristica se archetipo ignoto o l'agente fallisce.
# =============================================================================
import dataclasses
import alak_search_agent as base

# --- agenti dedicati + firma-Pokemon dell'archetipo (per il rilevamento) ---
_OPP_SIGS = None            # list[(set(pokemon_ids), agent_fn)]
_me_i = 0                   # nostro indice, per-mossa
_opp_fn = None             # agente avversario rilevato, per-mossa
_opp_is_mirror = False      # avversario Alakazam (specchio): usa l'euristica Alakazam
_base_greedy = base._greedy_pick   # euristica originale (fallback)
_MIRROR_SIG = {741, 742, 743, 66, 305, 65}   # linea Abra/Kadabra/Alakazam + Dudunsparce
try:
    import pool_agents as _pool           # fallback competente per archetipi IGNOTI
except Exception:
    _pool = None


def _load_opp_agents():
    import crustle_agent, archaludon_agent
    import mega_lucario_agent as ML, mega_abomasnow_agent as MA
    import dragapult_agent as DR, iono_official_agent as IO
    import zoroark_agent as ZO, grimmsnarl_agent as GR, mewtwo_rocket_agent as MW
    import official_agents as OA
    ML.my_deck = list(OA.OFFICIAL_DECKS['Mega_Lucario'])
    MA.my_deck = list(OA.OFFICIAL_DECKS['Mega_Abomasnow'])
    DR.my_deck = list(OA.OFFICIAL_DECKS['Dragapult'])
    IO.my_deck = list(OA.OFFICIAL_DECKS['Iono'])
    # firme = Pokemon caratteristici (ampliate -> rilevamento piu' precoce).
    # zoroark/grimmsnarl/mewtwo hanno il deck hardcoded: nessun override my_deck serve.
    return [
        ({344, 345, 756}, lambda o: crustle_agent.agent(o, 'Crustle')),      # Crustle/M-Kangaskhan
        ({169, 190, 57, 666}, archaludon_agent.agent),                       # Archaludon
        ({119, 120, 121}, DR.agent),                                         # Dragapult
        ({673, 674, 677, 678, 675, 676}, ML.agent),                          # Mega Lucario
        ({721, 722, 723}, MA.agent),                                         # Mega Abomasnow
        ({265, 268, 269, 270, 271}, IO.agent),                               # Iono
        ({292, 293, 303, 906, 257, 258, 141}, ZO.agent),                     # N's Zoroark ex
        ({646, 647, 648, 103, 104}, GR.agent),                               # Marnie's Grimmsnarl ex
        ({400, 401, 431, 434, 464}, MW.agent),                               # Team Rocket's Mewtwo ex
    ]


def _detect_opp(obs):
    """Archetipo avversario dalle carte visibili -> agente dedicato (o None)."""
    st = obs.current
    op = st.players[1 - st.yourIndex]
    seen = set()
    if op.active and op.active[0]:
        seen.add(op.active[0].id)
    for b in op.bench:
        if b:
            seen.add(b.id)
    for c in op.discard:
        seen.add(c.id)
    best, best_n = None, 0
    for sig, fn in _OPP_SIGS:
        k = len(sig & seen)
        if k > best_n:
            best_n, best = k, fn
    return best if best_n >= 1 else None


def _routed_greedy(obs):
    """Come base._greedy_pick, ma ai nodi-AVVERSARIO usa l'agente dedicato
    (mossa deterministica). Fallback all'euristica su errore/archetipo ignoto."""
    try:
        if obs.current.yourIndex != _me_i:
            fn = _opp_fn
            # archetipo IGNOTO e NON specchio -> pool_agent generico (piu' sensato
            # dell'euristica Alakazam su un deck non-Alakazam). Lo specchio resta su _base_greedy.
            if fn is None and _pool is not None and not _opp_is_mirror:
                fn = _pool.agent
            if fn is not None:
                sel = fn(dataclasses.asdict(obs))
                n = len(obs.select.option)
                sel = [i for i in (sel or []) if 0 <= i < n]
                if sel:
                    return sel, sel                   # choice, order (deterministico)
    except Exception:
        pass
    return _base_greedy(obs)


# instrada TUTTE le chiamate interne di base a _greedy_pick verso la versione ^
base._greedy_pick = _routed_greedy

# deck di QUESTO agente (per determinizzazione + registro)
ALAK_SEARCH_DECK = base.ALAK_SEARCH_DECK


def agent(obs_dict):
    global _OPP_SIGS, _me_i, _opp_fn, _opp_is_mirror
    if _OPP_SIGS is None:
        try:
            _OPP_SIGS = _load_opp_agents()            # rules-opponent nel search
        except Exception:
            _OPP_SIGS = []                            # agenti mancanti -> solo euristica
        base.my_deck = list(base.ALAK_SEARCH_DECK)    # deck nostro per la belief
    # deck-registration ROBUSTA: rispondi col mazzo senza dipendere dal parsing.
    if obs_dict.get('select') is None:
        base._search_ok = base._SEARCH_IMPORT_OK
        return list(base.my_deck)
    try:
        obs = base.to_observation_class(obs_dict)
    except Exception:
        return base._heuristic_agent(obs_dict)
    if obs.select is None:
        base._search_ok = base._SEARCH_IMPORT_OK
        return list(base.my_deck)
    _me_i = obs.current.yourIndex
    _opp_fn = _detect_opp(obs)                         # rileva l'avversario per questa mossa
    # specchio Alakazam? (decide il fallback: euristica Alakazam vs pool)
    op = obs.current.players[1 - _me_i]
    seen = set()
    if op.active and op.active[0]: seen.add(op.active[0].id)
    for b in op.bench:
        if b: seen.add(b.id)
    for c in op.discard: seen.add(c.id)
    _opp_is_mirror = bool(seen & _MIRROR_SIG)
    return base.agent(obs_dict)
