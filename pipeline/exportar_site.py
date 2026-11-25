"""Gera a API do site como arquivos JSON em atlas/static/api/, para publicar no GitHub Pages (sem servidor).

Entrada: data/atlas.db (somente leitura), pelas mesmas funções que o servidor local usa (atlas/app.py).
Saída: atlas/static/api/janelas.json e atlas/static/api/recordes/j<id da janela>.json e e<id da estação>.json.

Uso (na raiz do projeto, depois de python -m pipeline.janelas_completas):
    python -m pipeline.exportar_site
"""
from pathlib import Path
import json

from atlas import app

SAIDA = Path(__file__).resolve().parents[1] / 'atlas' / 'static' / 'api'


def gravar(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')


def main():
    gravar(SAIDA / 'janelas.json', app.janelas())
    with app.conectar_banco() as db:
        pares = db.execute('SELECT estacao_id, janela_id FROM recordes').fetchall()
    for estacao_id, janela_id in pares:
        if janela_id is None:
            gravar(SAIDA / 'recordes' / f'e{estacao_id}.json', app.recordes(estacao_id=estacao_id))
        else:
            gravar(SAIDA / 'recordes' / f'j{janela_id}.json', app.recordes(janela_id=janela_id))
    print(f'{len(pares)} arquivos de recordes e janelas.json em {SAIDA}')


if __name__ == '__main__':
    main()
