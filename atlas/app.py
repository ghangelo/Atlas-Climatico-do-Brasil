"""Servidor do Atlas: estações com trechos de pelo menos 10 anos de precipitação e temperatura juntas.

Lê só data/atlas.db (janelas, tendência, Köppen e recordes já calculados pelo pipeline).
Execute na pasta principal:  python -m atlas.app   e acesse http://127.0.0.1:8001
"""
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import os
import sqlite3

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ.parent / 'data' / 'atlas.db'
PORTA = int(os.environ.get('ATLAS_PORTA', '8001'))


def conectar_banco():
    if not BANCO.is_file():
        raise FileNotFoundError('Banco do Atlas não encontrado. Execute python -m pipeline.janelas_completas.')
    return closing(sqlite3.connect(BANCO.resolve().as_uri() + '?mode=ro', uri=True))


def janelas():
    with conectar_banco() as db:
        db.row_factory = sqlite3.Row
        linhas = db.execute('''SELECT j.id, j.estacao_id, j.inicio, j.fim, j.dias, j.meses, j.chuva_mensal, j.temperatura_mensal, j.dias_estimados,
                j.clima_chuva, j.clima_temperatura, j.serie_anual, j.tendencia, j.koppen, j.koppen_alternativas, e.altitude, e.codigo, e.nome, e.tipo, e.latitude, e.longitude
            FROM janelas j JOIN estacoes e ON e.id = j.estacao_id
            ORDER BY e.nome, e.codigo, j.inicio''').fetchall()
    return {'janelas': [{'id': r['id'], 'estacao_id': r['estacao_id'], 'inicio': r['inicio'], 'fim': r['fim'], 'anos': round(r['dias'] / 365.25, 1),
                         'meses': r['meses'], 'estimados_pct': round(100 * r['dias_estimados'] / r['dias'], 1),
                         'chuva_mensal': r['chuva_mensal'], 'temperatura_mensal': r['temperatura_mensal'],
                         'clima_chuva': json.loads(r['clima_chuva']), 'clima_temperatura': json.loads(r['clima_temperatura']),
                         'serie_anual': json.loads(r['serie_anual']), 'tendencia': json.loads(r['tendencia']),
                         'koppen': r['koppen'], 'koppen_alternativas': json.loads(r['koppen_alternativas']),
                         'altitude': r['altitude'],
                         'codigo': r['codigo'], 'nome': r['nome'], 'tipo': r['tipo'],
                         'lat': r['latitude'], 'lon': r['longitude']} for r in linhas]}


def recordes(janela_id=None, estacao_id=None):
    """Recordes do trecho (janela_id) ou da série completa da estação (estacao_id)."""
    with conectar_banco() as db:
        if janela_id is not None:
            linha = db.execute('SELECT grupos FROM recordes WHERE janela_id = ?', (janela_id,)).fetchone()
        else:
            linha = db.execute('SELECT grupos FROM recordes WHERE estacao_id = ? AND janela_id IS NULL', (estacao_id,)).fetchone()
    if linha is None:
        raise ValueError('Recordes não encontrados.')
    return {'grupos': json.loads(linha[0])}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RAIZ / 'static'), **kwargs)

    def enviar(self, status, corpo):
        dados = json.dumps(corpo, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def responder(self, consulta):
        try:
            return self.enviar(200, consulta())
        except (ValueError, OverflowError) as exc:  # OverflowError: id maior que o inteiro do SQLite
            return self.enviar(400, {'erro': str(exc)})
        except (FileNotFoundError, sqlite3.Error) as exc:
            return self.enviar(503, {'erro': str(exc)})

    def do_GET(self):
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        if url.path == '/api/recordes':
            def consulta():
                if 'janela' in q:
                    return recordes(janela_id=int(q['janela'][0]))
                return recordes(estacao_id=int(q.get('estacao', [''])[0]))
            return self.responder(consulta)
        if url.path == '/api/janelas':
            return self.responder(janelas)
        return super().do_GET()

    def list_directory(self, path):  # sem lista de arquivos ao abrir uma pasta
        self.send_error(404)


if __name__ == '__main__':
    servidor = ThreadingHTTPServer(('127.0.0.1', PORTA), Handler)
    print(f'Atlas disponível em http://127.0.0.1:{PORTA}', flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
