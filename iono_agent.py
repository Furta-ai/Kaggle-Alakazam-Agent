"""Agente dedicato al mazzo IONO'S VOLTORB (mono-prize scalante).
Voltorb (265) Voltaic Chain = 20 + 20 per ogni energia Lightning attaccata a TUTTI i tuoi
Pokemon Iono -> l'agente generico lo ignora (danno base 20). Qui calcoliamo il danno REALE
scalato. Motore: Bellibolt ex (269, Electric Streamer = accelera Lightning dalla mano),
Kilowattrel (271, Flashing Draw = scarta Lightning per pescare 3), Levincia (stadio).
Riusa i building block di pool_agents.
"""
import io
import contextlib

import main as M
import pool_agents as POOL
from pool_agents import _DB, _ATTACKS, _is_pokemon, _pk_is_attacker
from cg.api import OptionType, SelectType, to_observation_class

IONO_MON = {265, 266, 268, 269, 270, 271}
VOLTORB, BELLIBOLT, KILOWATTREL, ELECTRODE = 265, 269, 271, 266
VOLTAIC_CHAIN, LIGHTNING, LEVINCIA = 363, 4, 1254


def _lightning_on_iono(st):
    total = 0
    pks = []
    if st and getattr(st, 'active', None):
        pks += [p for p in st.active if p]
    if st and getattr(st, 'bench', None):
        pks += [p for p in st.bench if p]
    for p in pks:
        if p and p.id in IONO_MON:
            for e in (getattr(p, 'energyCards', None) or []):
                if getattr(e, 'id', None) == LIGHTNING:
                    total += 1
    return total


def _atk_dmg(o, st):
    aid = getattr(o, 'attackId', None)
    if aid == VOLTAIC_CHAIN:
        return 20 + 20 * _lightning_on_iono(st)
    a = _ATTACKS.get(aid)
    return getattr(a, 'damage', 0) if a else 0


def decide(P, options):
    def typ(o):
        return P.get_option_type(o)

    def cid(o):
        return P.get_option_card_id(o)

    def find(pred):
        for i, o in enumerate(options):
            try:
                if pred(o):
                    return i
            except Exception:
                continue
        return -1

    st = P.my_state
    opp = P.opp_state
    bench = [p for p in (getattr(st, 'bench', None) or []) if p]
    oa = opp.active[0] if opp and getattr(opp, 'active', None) and opp.active and opp.active[0] else None
    opp_hp = getattr(oa, 'hp', 9999) if oa else 9999
    hand_n = len(st.hand) if st and getattr(st, 'hand', None) else getattr(st, 'handCount', 0)
    deck_ct = getattr(st, 'deckCount', 60)

    attacks = [(i, _atk_dmg(o, st)) for i, o in enumerate(options) if typ(o) == OptionType.ATTACK]

    # 0. LETALE (danno scalato di Voltaic Chain incluso)
    if attacks and oa:
        kos = [(i, d) for i, d in attacks if d >= opp_hp]
        if kos:
            return [max(kos, key=lambda x: x[1])[0]]

    # 1. EVOLVI (Bellibolt ex, Kilowattrel, Electrode)
    i = find(lambda o: typ(o) == OptionType.EVOLVE)
    if i >= 0:
        return [i]

    # 2. ABILITA' (Electric Streamer = accelera Lightning; Flashing Draw = pesca)
    i = find(lambda o: typ(o) == OptionType.ABILITY)
    if i >= 0:
        return [i]

    # 3. PRESENZA IN CAMPO
    if len(bench) < 3:
        i = find(lambda o: typ(o) == OptionType.PLAY and _is_pokemon(cid(o)))
        if i >= 0:
            return [i]

    # 4. STADIO Levincia (accelera Lightning)
    cur_stad = None
    o_ = getattr(P, 'obs', None)
    if o_ is not None and o_.current is not None and getattr(o_.current, 'stadium', None):
        s = o_.current.stadium
        if s and s[0] is not None:
            cur_stad = s[0].id
    if cur_stad != LEVINCIA:
        i = find(lambda o: typ(o) == OptionType.PLAY and cid(o) == LEVINCIA)
        if i >= 0:
            return [i]

    # 5. ENERGIA Lightning su un Iono SICURO (Bellibolt tank 280HP) -> Voltaic Chain scala
    #    senza rischiare l'energia su Voltorb fragile (70HP).
    attach_opts = [i for i, o in enumerate(options) if typ(o) == OptionType.ATTACH]
    if attach_opts:
        def _tgt(o):
            area = getattr(o, 'inPlayArea', None); idx = getattr(o, 'inPlayIndex', None)
            if area == 4 and st.active:
                return st.active[0]
            if area == 5 and getattr(st, 'bench', None) and idx is not None and idx < len(st.bench):
                return st.bench[idx]
            return None
        best, bh = -1, -1
        for i in attach_opts:
            tp = _tgt(options[i])
            if tp and tp.id in IONO_MON:
                h = getattr(tp, 'maxHp', 0) + (1000 if tp.id == BELLIBOLT else 0)
                if h > bh:
                    bh, best = h, i
        return [best if best >= 0 else attach_opts[0]]

    # 6. PESCA supporter se mano scarna e mazzo ok
    if hand_n < 6 and deck_ct > 4:
        i = find(lambda o: typ(o) == OptionType.PLAY and _DB.get(cid(o)) and _DB[cid(o)].cardType == 3)
        if i >= 0:
            return [i]

    # 7. ITEM ricerca
    if hand_n < 8 and deck_ct > 3:
        i = find(lambda o: typ(o) == OptionType.PLAY and _DB.get(cid(o)) and _DB[cid(o)].cardType in (1, 2))
        if i >= 0:
            return [i]

    # 8. ATTACCA col danno REALE piu' alto (Voltaic Chain scalato incluso)
    if attacks:
        return [max(attacks, key=lambda x: x[1])[0]]

    # 9. anti-lock retreat
    if bench and any(_pk_is_attacker(p.id) for p in bench):
        i = find(lambda o: typ(o) == OptionType.RETREAT)
        if i >= 0:
            return [i]

    for pred in (lambda o: typ(o) == OptionType.PLAY, lambda o: typ(o) == OptionType.ATTACH):
        i = find(pred)
        if i >= 0:
            return [i]
    i = find(lambda o: typ(o) == OptionType.END)
    return [i] if i >= 0 else [0]


def _submenu(P, obs, options):
    def cid(o):
        return P.get_option_card_id(o)
    ctx = getattr(obs.select, 'context', None)
    st = P.my_state
    # Electric Streamer / effetti "quanti": massimizza (accelera più Lightning possibile)
    nums = [(j, getattr(o, 'number', None)) for j, o in enumerate(options)
            if P.get_option_type(o) == OptionType.NUMBER]
    nums = [(j, n) for j, n in nums if n is not None]
    if nums:
        return [max(nums, key=lambda x: x[1])[0]]
    if ctx in {1, 3, 4}:
        # promuovi Voltorb se carico (mono-prize win-con), altrimenti il miglior attaccante
        if _lightning_on_iono(st) >= 5:
            i = next((j for j, o in enumerate(options) if cid(o) == VOLTORB), -1)
            if i >= 0:
                return [i]
        best_i, best = -1, -10 ** 9
        for j, o in enumerate(options):
            c = cid(o); cd = _DB.get(c)
            sc = (5000 if _pk_is_attacker(c) else 0) + (cd.hp if cd else 0)
            if sc > best:
                best_i, best = j, sc
        if best_i >= 0:
            return [best_i]
    return list(range(min(obs.select.maxCount, len(options))))


def agent(obs_dict, deck_name=None):
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return None
    P = M.GameStateParser()
    with contextlib.redirect_stdout(io.StringIO()):
        P.update(obs)
        P.obs = obs
    if obs.select.type == SelectType.MAIN:
        with contextlib.redirect_stdout(io.StringIO()):
            return decide(P, obs.select.option)
    return _submenu(P, obs, obs.select.option)
