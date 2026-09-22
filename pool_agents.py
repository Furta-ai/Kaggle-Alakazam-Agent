"""Pool di AGENTI RULE-BASED per il self-play AlphaZero (avversari del net-MCTS).

Sostituisce l'avversario random: ogni mazzo del pool e' pilotato da un motore
rule-based DATA-DRIVEN che legge stage/abilita'/attacchi da CARD_DB, quindi esegue
di fatto il motore di ogni archetipo (evoluzioni che triggerano Punk Up/Assemble
Alloy/Jewel Seeker, abilita' di pesca come Teal Dance/Recon Directive, accelerazione,
attacco letale con consapevolezza dei premi ex=2 / mega ex=3).

Il mazzo avversario e' scelto a caso con probabilita' PROPORZIONALE alle frequenze
osservate nei replay (opponent_decks.POPULARITY). Cosi' la rete impara soprattutto
contro cio' che incontra davvero in ladder (Crustle domina), ma vede tutto il campo.

Uso principale:
    import pool_agents as POOL
    name, deck = POOL.sample_pool()          # mazzo pesato sulle frequenze
    sel = POOL.agent(obs_dict, name)         # mossa dell'avversario
"""
import io
import contextlib
import random

import main as M
from cg.api import OptionType, SelectType, to_observation_class, all_card_data

try:
    from cg.api import all_attack
    _ATTACKS = {a.attackId: a for a in all_attack()}
except Exception:
    _ATTACKS = {}

_DB = {c.cardId: c for c in all_card_data()}


# ---------------------------------------------------------------- classificazione
def _card_type(cid):
    c = _DB.get(cid)
    return c.cardType if c else -1            # 0=Pkmn 1=Item 2=Tool 3=Supporter 4=Stadio 5=Energia


def _is_pokemon(cid):
    return _card_type(cid) == 0


def _pk_is_attacker(cid):
    """Il Pokemon ha almeno un attacco che infligge danni (bersaglio dell'energia)."""
    c = _DB.get(cid)
    if not c or not getattr(c, 'attacks', None):
        return False
    for aid in c.attacks:
        a = _ATTACKS.get(aid)
        if a and getattr(a, 'damage', 0) > 0:
            return True
    return False


def _energy(pk):
    if not pk:
        return 0
    return len(getattr(pk, 'energyCards', None) or getattr(pk, 'energies', []) or [])


# ---------------------------------------------------------------- motore generico
def decide_generic(P, options):
    """Scala di priorita' robusta e intelligente, valida per QUALSIASI mazzo del pool."""
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
    active = st.active[0] if st and getattr(st, 'active', None) and st.active and st.active[0] else None
    bench_raw = list(st.bench) if st and getattr(st, 'bench', None) else []
    bench = [p for p in bench_raw if p]
    opp_active = opp.active[0] if opp and getattr(opp, 'active', None) and opp.active and opp.active[0] else None
    opp_hp = getattr(opp_active, 'hp', 9999) if opp_active else 9999
    hand_n = len(st.hand) if st and getattr(st, 'hand', None) else getattr(st, 'handCount', 0)
    deck_ct = getattr(st, 'deckCount', 60) if st else 60

    def atk_dmg(o):
        a = _ATTACKS.get(getattr(o, 'attackId', None))
        return getattr(a, 'damage', 0) if a else 0

    attacks = [(i, atk_dmg(o)) for i, o in enumerate(options) if typ(o) == OptionType.ATTACK]

    # 0. LETALE: l'attacco piu' forte che mette KO l'attivo avversario (chiudi il premio)
    if attacks and opp_active:
        kos = [(i, d) for i, d in attacks if d >= opp_hp]
        if kos:
            return [max(kos, key=lambda x: x[1])[0]]

    # 1. EVOLVI (triggera i motori all'evoluzione: Punk Up, Assemble Alloy, Jewel Seeker...)
    i = find(lambda o: typ(o) == OptionType.EVOLVE)
    if i >= 0:
        return [i]

    # 2. ABILITA' (motori di pesca/accelerazione: Teal Dance, Recon Directive, Lunar Cycle...)
    i = find(lambda o: typ(o) == OptionType.ABILITY)
    if i >= 0:
        return [i]

    # 3. PRESENZA IN CAMPO: metti un Pokemon base in panchina se il board e' scarno
    if len(bench) < 3:
        i = find(lambda o: typ(o) == OptionType.PLAY and _is_pokemon(cid(o)))
        if i >= 0:
            return [i]

    # 4. STADIO: gioca il nostro se non e' gia' in campo
    cur_stad = None
    o_ = getattr(P, 'obs', None)
    if o_ is not None and o_.current is not None and getattr(o_.current, 'stadium', None):
        s = o_.current.stadium
        if s and s[0] is not None:
            cur_stad = s[0].id
    i = find(lambda o: typ(o) == OptionType.PLAY and _card_type(cid(o)) == 4 and cid(o) != cur_stad)
    if i >= 0:
        return [i]

    # 5. ENERGIA sull'attaccante (attivo se attacca, altrimenti l'attaccante piu' carico)
    if find(lambda o: typ(o) == OptionType.ATTACH) >= 0:
        i = find(lambda o: typ(o) == OptionType.ATTACH and getattr(o, 'inPlayArea', None) == 4
                 and active and _pk_is_attacker(active.id))
        if i < 0:
            best_j, best_e = -1, -1
            for j, pk in enumerate(bench_raw):
                if pk and _pk_is_attacker(pk.id) and _energy(pk) > best_e:
                    best_j, best_e = j, _energy(pk)
            if best_j >= 0:
                i = find(lambda o: typ(o) == OptionType.ATTACH
                         and getattr(o, 'inPlayArea', None) == 5
                         and getattr(o, 'inPlayIndex', None) == best_j)
        if i < 0:
            i = find(lambda o: typ(o) == OptionType.ATTACH)
        if i >= 0:
            return [i]

    # 6. SUPPORTER (pesca/ricerca) se mano scarna e mazzo non a rischio deck-out
    if hand_n < 6 and deck_ct > 4:
        i = find(lambda o: typ(o) == OptionType.PLAY and _card_type(cid(o)) == 3)
        if i >= 0:
            return [i]

    # 7. ITEM (ricerca/pesca/tool) se stiamo ancora montando e c'e' mazzo
    if hand_n < 8 and deck_ct > 3:
        i = find(lambda o: typ(o) == OptionType.PLAY and _card_type(cid(o)) in (1, 2))
        if i >= 0:
            return [i]

    # 8. ATTACCA col piu' forte disponibile
    if attacks:
        return [max(attacks, key=lambda x: x[1])[0]]

    # 9. RITIRATA anti-lock: attivo non attacca ma un attaccante in panchina e' pronto
    if not attacks and any(_pk_is_attacker(p.id) and _energy(p) >= 1 for p in bench):
        i = find(lambda o: typ(o) == OptionType.RETREAT)
        if i >= 0:
            return [i]

    # 10. fallback utile, altrimenti chiudi il turno
    for pred in (lambda o: typ(o) == OptionType.EVOLVE,
                 lambda o: typ(o) == OptionType.PLAY,
                 lambda o: typ(o) == OptionType.ATTACH,
                 lambda o: typ(o) == OptionType.ATTACK):
        i = find(pred)
        if i >= 0:
            return [i]
    i = find(lambda o: typ(o) == OptionType.END)
    return [i] if i >= 0 else [0]


def _submenu(P, obs, options):
    """Sottomenu context-aware: promuovi l'attaccante piu' carico, altrimenti default."""
    def cid(o):
        return P.get_option_card_id(o)
    ctx = getattr(obs.select, 'context', None)
    maxc = obs.select.maxCount
    if ctx in {1, 3, 4}:  # promozione / switch / setup attivo
        best_i, best_score = -1, -10 ** 9
        for i, o in enumerate(options):
            c = cid(o)
            sc = (5000 if _pk_is_attacker(c) else 0) + (_DB.get(c).hp if _DB.get(c) else 0)
            if sc > best_score:
                best_i, best_score = i, sc
        if best_i >= 0:
            return [best_i]
    return list(range(min(maxc, len(options))))


def agent(obs_dict, deck_name=None):
    """Punto d'ingresso avversario. Crustle usa l'agente dedicato (muro anti-ex)."""
    if deck_name == 'Crustle':
        import crustle_agent
        return crustle_agent.agent(obs_dict, deck_name)
    if deck_name == 'Iono_Bellibolt':
        import iono_agent
        return iono_agent.agent(obs_dict, deck_name)
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return None                       # il deck e' passato a battle_start dal chiamante
    P = M.GameStateParser()
    with contextlib.redirect_stdout(io.StringIO()):
        P.update(obs)
        P.obs = obs
    if obs.select.type == SelectType.MAIN:
        with contextlib.redirect_stdout(io.StringIO()):
            return decide_generic(P, obs.select.option)
    return _submenu(P, obs, obs.select.option)


# ---------------------------------------------------------------- POOL DI MAZZI
def _d(s):
    return [int(x) for x in s.split(',')]


POOL_DECKS = {
    # --- mazzi forniti (validati LEGALI, 60 carte) ---
    'Dragapult_Base': _d('119,119,119,119,120,120,120,120,121,121,121,112,112,305,66,1071,140,235,1227,1227,1227,1227,1198,1198,1198,1182,1182,1182,1213,1152,1152,1152,1152,1086,1086,1086,1086,1121,1121,1121,1121,1120,1120,1120,1120,1097,1097,1080,1260,1260,5,5,5,5,2,2,2,7,7,7'),
    'Dragapult_Dusknoir': _d('119,119,119,119,120,120,120,120,121,121,121,131,131,132,133,112,112,235,140,1071,1227,1227,1227,1227,1198,1198,1198,1182,1182,1182,1231,1231,1121,1121,1121,1121,1152,1152,1152,1152,1086,1086,1086,1086,1079,1079,1079,1097,1097,1080,1260,1260,5,5,5,2,2,2,7,7'),
    'Dragapult_Blaziken': _d('119,119,119,119,120,120,120,120,121,121,410,410,411,326,326,112,112,791,140,272,235,1071,1227,1227,1227,1227,1182,1182,1182,1198,1198,1231,1213,1121,1121,1121,1121,1086,1086,1086,1086,1152,1152,1152,1079,1079,1079,1097,1097,1080,1256,1260,2,2,2,5,5,5,7,7'),
    'Slowking_Control': _d('162,162,162,162,163,163,305,305,66,66,144,144,140,184,115,224,550,1071,272,756,1227,1227,1227,1227,1225,1225,1225,1188,1188,1188,1121,1121,1121,1121,1152,1152,1152,1152,1146,1146,1146,1146,1097,1097,1097,1097,1123,1123,1248,1248,1248,1248,19,19,19,19,5,5,5,13'),
    'Ogerpon_Meganium': _d('96,96,96,96,402,402,403,403,404,404,708,708,709,709,710,710,1071,1071,235,140,1227,1227,1227,1227,1231,1231,1213,1213,1182,1182,1184,1201,1121,1121,1121,1121,1094,1094,1094,1094,1152,1152,1097,1080,1261,1261,1261,1261,1,1,1,1,1,1,1,1,1,1,1,1'),
    'RagingBolt_Ogerpon': _d('756,756,756,1071,1071,1071,96,96,96,63,63,184,184,272,108,75,140,978,209,1198,1198,1198,1198,1182,1182,1205,1205,1188,1227,1121,1121,1121,1121,1116,1116,1116,1116,1097,1097,1098,1098,1080,1250,1250,1250,1250,1,1,1,1,1,1,1,4,4,6,6,5,5,3'),
    'Alakazam_Hand': _d('741,741,741,741,742,742,742,742,743,743,743,305,305,305,66,66,66,222,858,343,142,140,1231,1231,1231,1231,1225,1225,1225,1225,1182,1182,1182,1184,1152,1152,1152,1152,1086,1086,1086,1086,1079,1079,1079,1081,1081,1129,1161,1161,1161,1264,1264,1264,19,19,19,19,5,13'),
    'Mega_Lucario_Base': _d('333,333,974,677,678,678,678,305,305,305,66,66,306,676,676,675,675,142,1227,1227,1227,1227,1182,1182,1182,1182,1225,1225,1152,1152,1152,1152,1142,1142,1142,1142,1141,1141,1141,1141,1086,1086,1121,1121,1174,1174,1252,1252,6,6,6,6,6,6,6,6,20,20,20,12'),
    'Starmie_Froslass': _d('860,860,860,104,104,861,861,1030,1030,1031,1031,112,112,112,305,305,66,66,306,235,1071,1227,1227,1227,1227,1225,1225,1182,1182,1198,1213,1229,1206,1086,1086,1086,1086,1152,1152,1152,1152,1121,1121,1121,1097,1097,1122,1156,1260,1260,1260,3,3,3,3,7,7,7,7,12'),
    'Kangaskhan_Wall': _d('175,175,233,160,160,126,756,756,184,184,24,112,858,144,210,414,1219,1219,1219,1219,1188,1188,1188,1182,1182,1182,1198,1198,1210,1147,1147,1147,1147,1122,1122,1122,1134,1134,1097,1121,1112,1126,1178,1257,1257,1252,1,1,1,1,4,4,4,4,8,8,11,11,7,7'),
    'TeamRocket_Mewtwo': _d('19,19,19,19,20,20,20,20,81,81,87,87,51,51,56,119,119,119,119,171,171,171,171,174,174,174,177,177,176,178,178,178,178,131,131,131,131,196,196,196,143,143,115,158,158,154,80,80,173,1,1,1,1,1,1,182,182,182,182,5'),
    'Crustle': _d('756,756,756,756,344,344,344,345,345,345,414,414,414,1182,1182,1182,1182,1227,1227,1227,1227,1219,1219,1219,1186,1186,1225,1225,1197,1190,1147,1147,1122,1122,1086,1121,1123,1123,1123,1159,1097,3,3,3,3,18,18,18,18,15,15,15,15,14,14,14,14,1,1,1')
}

# archetipi dai replay non coperti dai mazzi forniti (Crustle domina la ladder!)
try:
    import opponent_decks as _OD
    for _key, _name in [('crustle', 'Crustle'), ('cynthia_garchomp', 'Cynthia_Garchomp'),
                        ('marnie_grimmsnarl', 'Marnie_Grimmsnarl'), ('mega_abomasnow', 'Mega_Abomasnow'),
                        ('iono_bellibolt', 'Iono_Bellibolt')]:
        if _key in _OD.ARCHETYPE_DECKS:
            POOL_DECKS[_name] = list(_OD.ARCHETYPE_DECKS[_key])
except Exception:
    pass

# Iono Voltorb ricostruito PROPERLY (4 Voltorb + motore Lightning; il replay era filler-Erba)
POOL_DECKS['Iono_Bellibolt'] = (
    [265] * 4 + [266] * 1 + [269] * 3 + [268] * 3 + [271] * 3 + [270] * 3
    + [4] * 16
    + [1086] * 4 + [1121] * 4 + [1254] * 3 + [1097] * 3 + [1227] * 4
    + [1182] * 2 + [1152] * 2 + [1122] * 2 + [1233] * 2 + [1110] * 1)

# Crustle: mazzo-muro AGGIORNATO (nuovo crustle_agent). Override DOPO opponent_decks
# cosi' vince: Crustle/Kabutops line + Jumbo Ice/Cook/Hero's Cape + Cheren + energie.
POOL_DECKS['Crustle'] = (
    [344] * 4 + [345] * 4 + [1147] * 4 + [1159] * 1 + [1264] * 4 + [1212] * 4
    + [1224] * 4 + [18] * 4 + [11] * 4 + [1086] * 4 + [14] * 4 + [1] * 19)

# Pesi = frequenza nei replay (POPULARITY). 'unknown'=69 distribuito tra Dragapult/
# Ogerpon/Slowking; 'archaludon' escluso (e' lo specchio, gestito da MIRROR_FRAC).
POOL_WEIGHTS = {
    'Crustle': 293,
    'Cynthia_Garchomp': 44,
    'Alakazam_Hand': 34,
    'Marnie_Grimmsnarl': 27,
    'Mega_Lucario_Base': 25,
    'Starmie_Froslass': 23,
    'TeamRocket_Mewtwo': 18,
    'Mega_Abomasnow': 17,
    'Kangaskhan_Wall': 10,
    'Iono_Bellibolt': 4,
    'Dragapult_Base': 20, 'Dragapult_Dusknoir': 12, 'Dragapult_Blaziken': 8,
    'RagingBolt_Ogerpon': 12, 'Ogerpon_Meganium': 8, 'Slowking_Control': 9,
}


def sample_pool():
    """Ritorna (nome, mazzo) scelto con probabilita' proporzionale alle frequenze replay."""
    names = [n for n in POOL_DECKS]
    weights = [POOL_WEIGHTS.get(n, 10) for n in names]
    name = random.choices(names, weights=weights, k=1)[0]
    return name, list(POOL_DECKS[name])
