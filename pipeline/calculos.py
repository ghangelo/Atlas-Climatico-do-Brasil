"""Classificação de Köppen-Geiger usada pelo pipeline."""
SENSIBILIDADE_T = 1.0   # °C somados a todos os meses
SENSIBILIDADE_P = 0.05  # fração da chuva de todos os meses


def koppen_alternativas(temperatura, chuva):
    """Outras classes que aparecem com pequenas variações (±1 °C ou ±5% de chuva). Lista vazia se a classe é estável."""
    base = koppen(temperatura, chuva)
    alt = set()
    for s in (-1, 1):
        alt.add(koppen([x + s * SENSIBILIDADE_T for x in temperatura], chuva))
        alt.add(koppen(temperatura, [x * (1 + s * SENSIBILIDADE_P) for x in chuva]))
    return sorted(alt - {base})


def koppen(temperatura, chuva):
    """Classe de Köppen-Geiger (Beck et al., 2018) a partir de 12 médias mensais (°C) e totais (mm)."""
    if len(temperatura) != 12 or len(chuva) != 12:
        raise ValueError('São necessários 12 meses de temperatura e precipitação.')
    t, p = temperatura, chuva
    apr = list(range(3, 9))
    octo = [9, 10, 11, 0, 1, 2]
    verao, inverno = (apr, octo) if sum(t[i] for i in apr) > sum(t[i] for i in octo) else (octo, apr)
    ps, pw = [p[i] for i in verao], [p[i] for i in inverno]
    anual, media = sum(p), sum(t) / 12
    limiar = 2 * media + (28 if sum(ps) > .7 * anual else 0 if sum(pw) > .7 * anual else 14)
    if anual < 10 * limiar:
        return 'B' + ('W' if anual < 5 * limiar else 'S') + ('h' if media >= 18 else 'k')
    frio, quente = min(t), max(t)
    if frio >= 18:
        return 'Af' if min(p) >= 60 else 'Am' if min(p) >= 100 - anual / 25 else 'Aw'
    if quente <= 10:
        return 'ET' if quente > 0 else 'EF'
    seca_s = min(ps) < 40 and min(ps) < max(pw) / 3
    seca_w = min(pw) < max(ps) / 10
    estacao = ('s' if sum(pw) > sum(ps) else 'w') if seca_s and seca_w else 's' if seca_s else 'w' if seca_w else 'f'
    quentes = sum(x > 10 for x in t)
    terceira = 'a' if quente >= 22 else 'b' if quentes >= 4 else 'd' if frio < -38 else 'c'
    return ('C' if frio > 0 else 'D') + estacao + terceira

