# Arquitetura

## Dados e aplicação

1. Os arquivos originais do INMET ficam em `data/raw/inmet/` (convencionais e automáticas, uma estação por CSV diário).
2. `pipeline/criar_fonte.py` cria `data/fonte.db`, com as tabelas `estacoes` e `diario`. Não altera os dados.
3. `pipeline/preencher_ml.py` lê `fonte.db` e grava `data/preenchido.db`: estimativas diárias do modelo, validação por estação e configuração. Só preenche lacunas de até 30 dias. Ver [pipeline/README.md](../pipeline/README.md).
4. `pipeline/preparar_dados.py` cria `data/combinado.db` a partir de `fonte.db` e `preenchido.db`: tabela `dados` (diária, com original ou estimativa) e tabela `mensal`.
5. `pipeline/janelas_completas.py` cria `data/atlas.db`: trechos de dias seguidos com pelo menos 10 anos em que a estação tem precipitação e temperatura juntas (para a classificação de Köppen). Guarda o total mensal médio de chuva e a média mensal de temperatura, usando só meses inteiros.
6. `atlas/app.py` é o servidor HTTP: entrega `atlas/static/` e a API (`/api/janelas` e `/api/recordes`). Lê `atlas.db` em modo somente leitura.
7. `atlas/static/app.js` só desenha: controles, mapa, popups e tabela.

A validação espacial por leave-one-out (`validacao.py`) e seus relatórios foram para `arquivo_morto/`: o site não desenha mais uma superfície interpolada.

## Endpoints

| Caminho | Resultado |
| --- | --- |
| `/api/janelas` ||| `/api/janelas` ||| `/api/janelas` | Trechos de cada estação, com início, fim, anos, meses completos, parcela de dias estimados, chuva mensal e temperatura mensal |

Id inválido ou inexistente em `/api/recordes` devolve HTTP 400; banco ausente, HTTP 503. O filtro por tipo de estação é feito no navegador.

## Testes

```bash
python -m unittest discover -s tests -t .
```

Os testes usam dados sintéticos e não tocam em `data/`. Os bancos científicos não são reconstruídos nem auditados por esses testes.
