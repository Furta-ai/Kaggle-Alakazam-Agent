"""tournament.py - Round-robin tra tutti gli agenti disponibili.
Ogni coppia gioca N partite con start alternato. Stampa matrice vittorie e
classifica (winrate medio). Env: TOUR_N (partite/coppia, default 10).
"""
import os, sys, io, contextlib, random, time
SUBM = os.path.dirname(os.path.abspath(__file__))
os.chdir(SUBM); sys.path.insert(0, SUBM)
from cg.game import battle_start, battle_select, battle_finish

N = int(os.environ.get("TOUR_N", "10"))


def build_agents():
    import official_agents as OA
    import crustle_agent as C, archaludon_agent as ARCHA
    import pool_agents as POOL
    import alak_search_ro as AL          # variante con rules-opponent nel search
    archa_deck = [int(x) for x in open("deck_archa.csv").read().replace(',', ' ').split() if x.strip()][:60]
    ag = {
        'alak_search_ro': (AL.agent, list(AL.ALAK_SEARCH_DECK)),
        'Crustle': (lambda o: C.agent(o, 'Crustle'), list(POOL.POOL_DECKS['Crustle'])),
        'Archaludon': (ARCHA.agent, archa_deck),
    }
    for nm in ('Mega_Lucario', 'Mega_Abomasnow', 'Dragapult', 'Iono'):
        ag[nm] = OA.AGENTS[nm]
    return ag


def play(f0, d0, f1, d1):
    """Ritorna 0/1 (vincitore player) o None (patta/errore)."""
    with contextlib.redirect_stdout(io.StringIO()):
        obs, st = battle_start(d0, d1)
        if st.errorPlayer != -1:
            return None
        L = 0
        while obs["current"]["result"] < 0 and L < 2000:
            yi = obs["current"]["yourIndex"]
            sel = f0(obs) if yi == 0 else f1(obs)
            obs = battle_select(sel); L += 1
        battle_finish()
    r = obs["current"]["result"]
    return None if r == 2 else r


def main():
    AG = build_agents()
    names = list(AG)
    print(f"TORNEO round-robin | {len(names)} agenti | {N} partite/coppia (start alternato)\n"
          f"agenti: {names}\n", flush=True)
    wins = {n: 0 for n in names}
    games = {n: 0 for n in names}
    matrix = {a: {b: '' for b in names} for a in names}

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, da = AG[a]; fb, db = AG[b]
            wa = wb = 0; t0 = time.time()
            for g in range(N):
                if g % 2 == 0:
                    r = play(fa, da, fb, db)          # a=P0
                    if r == 0: wa += 1
                    elif r == 1: wb += 1
                else:
                    r = play(fb, db, fa, da)          # b=P0
                    if r == 0: wb += 1
                    elif r == 1: wa += 1
            tot = wa + wb
            wins[a] += wa; games[a] += tot
            wins[b] += wb; games[b] += tot
            matrix[a][b] = f"{wa}-{wb}"; matrix[b][a] = f"{wb}-{wa}"
            print(f"  {a:14s} vs {b:14s}: {wa}-{wb}  ({100*wa/max(1,tot):.0f}% per {a}, {time.time()-t0:.0f}s)", flush=True)

    print("\n=== CLASSIFICA (winrate medio) ===", flush=True)
    for n in sorted(names, key=lambda x: -wins[x] / max(1, games[x])):
        print(f"  {n:14s} {100*wins[n]/max(1,games[n]):5.1f}%  ({wins[n]}/{games[n]})", flush=True)


if __name__ == "__main__":
    main()
