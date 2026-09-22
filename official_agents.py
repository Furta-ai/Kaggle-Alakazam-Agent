# =============================================================================
#  official_agents.py - Registro degli agenti-avversario ufficiali (sample deck).
#  -----------------------------------------------------------------------------
#  Ogni agente legge deck.csv (= il NOSTRO Alakazam) al momento dell'import per la
#  propria conoscenza del mazzo. Qui, dopo l'import, sovrascriviamo il loro global
#  `my_deck` col mazzo CORRETTO -> giocano col loro mazzo (Dragapult ne usa il
#  card-counting). Nel nostro harness il mazzo fisico va comunque passato a
#  battle_start dal chiamante (usa OFFICIAL_DECKS).
# =============================================================================
def _expand(pairs):
    """(card_id, count) -> lista espansa; verifica 60 carte."""
    d = []
    for cid, n in pairs:
        d += [cid] * n
    assert len(d) == 60, f"deck non da 60: {len(d)}"
    return d


OFFICIAL_DECKS = {
    'Mega_Lucario': _expand([
        (673, 2), (674, 2), (675, 2), (676, 3), (677, 3), (678, 4), (1102, 4),
        (1123, 2), (1141, 4), (1142, 4), (1152, 4), (1159, 1), (1182, 2), (1192, 4),
        (1227, 4), (1252, 2), (6, 13)]),
    'Mega_Abomasnow': _expand([
        (721, 2), (722, 4), (723, 4), (1121, 4), (1126, 1), (1192, 4), (1227, 4),
        (1262, 3), (3, 34)]),
    'Dragapult': _expand([
        (119, 4), (120, 4), (121, 3), (140, 1), (184, 1), (235, 2), (1071, 1),
        (1079, 2), (1080, 1), (1086, 4), (1097, 2), (1120, 4), (1121, 4), (1152, 3),
        (1156, 1), (1182, 3), (1198, 4), (1210, 2), (1227, 4), (1256, 2), (2, 4), (5, 4)]),
    'Iono': _expand([
        (265, 3), (268, 3), (269, 3), (270, 3), (271, 3), (1086, 3), (1097, 2),
        (1110, 1), (1118, 1), (1121, 3), (1152, 2), (1227, 4), (1233, 4), (1254, 3),
        (4, 22)]),
}


def _load():
    import mega_lucario_agent as ML
    import mega_abomasnow_agent as MA
    import dragapult_agent as DR
    import iono_official_agent as IO
    ML.my_deck = list(OFFICIAL_DECKS['Mega_Lucario'])
    MA.my_deck = list(OFFICIAL_DECKS['Mega_Abomasnow'])
    DR.my_deck = list(OFFICIAL_DECKS['Dragapult'])
    IO.my_deck = list(OFFICIAL_DECKS['Iono'])
    return {
        'Mega_Lucario': (ML.agent, OFFICIAL_DECKS['Mega_Lucario']),
        'Mega_Abomasnow': (MA.agent, OFFICIAL_DECKS['Mega_Abomasnow']),
        'Dragapult': (DR.agent, OFFICIAL_DECKS['Dragapult']),
        'Iono': (IO.agent, OFFICIAL_DECKS['Iono']),
    }


AGENTS = _load()   # {nome: (agent_fn, deck)}
