"""make_vis.py - Genera vis.json per una coppia di agenti (da caricare in
visualizer.html -> visualizzatore Heroz). Vede come gioca ogni agente.

Uso:  python make_vis.py <agente0> <agente1> [out.json] [seed]
Agenti: net, mcts, Crustle, Mega_Lucario, Mega_Abomasnow, Dragapult, Iono, Archaludon
Es.:  python make_vis.py mcts Archaludon vis_mcts_archa.json
"""
import os, sys, json, random
SUBM = os.path.dirname(os.path.abspath(__file__))
os.chdir(SUBM); sys.path.insert(0, SUBM)
from cg.game import battle_start, battle_select, battle_finish, visualize_data

AGENT_DECK = [int(x) for x in open("deck.csv").read().replace(',', ' ').split() if x.strip()][:60]


def _archa_deck():
    return [int(x) for x in open("deck_archa.csv").read().replace(',', ' ').split() if x.strip()][:60]


def resolve(name):
    """nome -> (agent_fn, deck). Import pigro (mcts carica i modelli)."""
    n = name.lower()
    if n == "net":
        import bc_agent as B; return B.agent, list(AGENT_DECK)
    if n == "mcts":
        import agent_mcts_mio as A; return A.agent, list(A.AGENT_DECK)
    if n == "archaludon":
        import archaludon_agent as AR; return AR.agent, _archa_deck()
    if name in ("Crustle", "crustle"):
        import pool_agents as P, crustle_agent as C
        return (lambda o: C.agent(o, 'Crustle')), list(P.POOL_DECKS['Crustle'])
    if n in ("alak_search", "alak", "alakazam"):
        import alak_search_agent as AL
        AL.my_deck = list(AL.ALAK_SEARCH_DECK)      # deck corretto per la determinizzazione
        return AL.agent, list(AL.ALAK_SEARCH_DECK)
    import official_agents as OA
    if name in OA.AGENTS:
        fn, deck = OA.AGENTS[name]; return fn, list(deck)
    raise ValueError(f"agente sconosciuto: {name}")


def main():
    a0_name = sys.argv[1] if len(sys.argv) > 1 else "mcts"
    a1_name = sys.argv[2] if len(sys.argv) > 2 else "Archaludon"
    out = sys.argv[3] if len(sys.argv) > 3 else "vis.json"
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    random.seed(seed)

    fn0, deck0 = resolve(a0_name)
    fn1, deck1 = resolve(a1_name)
    print(f"[vis] {a0_name} (P0) vs {a1_name} (P1) | seed {seed}", flush=True)

    obs_dict, st = battle_start(deck0, deck1)
    if st.errorPlayer != -1:
        print("errore battle_start"); return
    obs_log = [""]
    action_log = [None]
    L = 0
    while obs_dict["current"]["result"] < 0 and L < 2000:
        yi = obs_dict["current"]["yourIndex"]
        action = fn0(obs_dict) if yi == 0 else fn1(obs_dict)
        obs_dict.pop("search_begin_input", None)          # enorme: fuori dal log
        obs_log.append(obs_dict)
        action_log.append(action)
        obs_dict = battle_select(action)
        L += 1

    result = obs_dict["current"]["result"]
    vis = json.loads(visualize_data())
    n = min(len(vis), len(obs_log))
    for i in range(n):
        vis[i]["obs"] = obs_log[i]
        vis[i]["action"] = [action_log[i], action_log[i]]
    with open(out, "w") as f:
        json.dump(vis, f)
    battle_finish()

    winner = a0_name if result == 0 else a1_name if result == 1 else "patta"
    print(f"[vis] {L} mosse | vincitore: {winner} (result={result}) | steps vis: {len(vis)}", flush=True)
    print(f"[vis] salvato -> {os.path.join(SUBM, out)}  (caricalo in visualizer.html)", flush=True)


if __name__ == "__main__":
    main()
