// Atlas: uma marca fixa por estação, com séries de precipitação e temperatura juntas.
// Duas vistas na mesma página: mapa com lista (#/) e uma série (#/serie/ID), para o botão voltar funcionar.
// Azul e laranja ficam reservados aos dados de chuva e temperatura; a estação tem cor própria.
const CHUVA = '#1b5e96', CALOR = '#b1440f', TINTA = '#12212b', GRADE = '#d9e1e5';
// Continuidade: quanto maior a série contínua da estação, mais escuro o ponto (melhor para pior, do escuro ao claro).
const CLASSES = [
  {min: 20, cor: '#3f1052', nome: '20 anos ou mais'},
  {min: 15, cor: '#7a2e8e', nome: '15 a 20 anos'},
  {min: 12, cor: '#b27cc2', nome: '12 a 15 anos'},
  {min: 0, cor: '#e1c6ea', nome: 'Menos de 12 anos'},
];
const classeDe = anos => CLASSES.find(c => anos >= c.min);
const REDUZIR = matchMedia('(prefers-reduced-motion: reduce)').matches;
const TOQUE = matchMedia('(hover: none)');
const DESKTOP = matchMedia('(min-width: 62rem)');
const $ = id => document.getElementById(id);

function el(tag, texto, classe) {
  const e = document.createElement(tag);
  if (texto) e.textContent = texto;
  if (classe) e.className = classe;
  return e;
}
const numero = (v, casas) => v.toLocaleString('pt-BR', {minimumFractionDigits: casas, maximumFractionDigits: casas});
const comSinal = (v, casas) => v.toLocaleString('pt-BR', {minimumFractionDigits: casas, maximumFractionDigits: casas, signDisplay: 'exceptZero'});
const data = iso => iso.split('-').reverse().join('/');
const nomeDe = j => j.nome || j.codigo;
const tipoRede = j => (j.tipo === 'automatica' ? 'Automática' : 'Convencional');
const periodo = j => `${data(j.inicio)} a ${data(j.fim)}`;
const semAcento = s => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

// Busca JSON e lança erro com uma mensagem que diz o que fazer.
async function pedir(url) {
  let resposta;
  try { resposta = await fetch(url); } catch { throw new Error('Não foi possível falar com o servidor do Atlas. Confira se ele está em execução e tente de novo.'); }
  const dados = await resposta.json().catch(() => ({}));
  if (!resposta.ok) throw new Error(dados.erro || 'O servidor não conseguiu responder. Tente de novo.');
  return dados;
}

// ---------- Tabelas ----------
function tabela(legenda, cabecalho, linhas, ordenar) {
  const t = document.createElement('table');
  t.append(el('caption', legenda, 'sr-only'));
  const tr = document.createElement('tr');
  tr.append(...cabecalho.map(h => el('th', h)));
  const thead = document.createElement('thead');
  thead.append(tr);
  const tbody = document.createElement('tbody');
  for (const celulas of linhas) {
    const linha = document.createElement('tr');
    linha.append(...celulas.map(c => el('td', c)));
    tbody.append(linha);
  }
  t.append(thead, tbody);
  t.querySelectorAll('th').forEach(th => th.scope = 'col');
  // Colunas só de números alinham à direita (a vírgula decimal fica na mesma posição). A 1ª coluna nomeia a linha.
  cabecalho.forEach((_, c) => {
    if (c > 0 && linhas.length && linhas.every(l => /^-?[\d.]+(,\d+)?$/.test(l[c]))) {
      t.rows[0].cells[c].classList.add('num');
      [...tbody.rows].forEach(r => r.cells[c].classList.add('num'));
    }
  });
  if (ordenar) ordenavel(t);
  return t;
}

// Cada cabeçalho vira um botão: 1º clique crescente, 2º decrescente. A 1ª coluna (dia, mês, ano) volta à ordem do
// calendário; nas demais vale o número no início da célula. Células sem valor ficam no fim.
function ordenavel(t) {
  const tbody = t.tBodies[0];
  [...tbody.rows].forEach((linha, i) => { linha.dataset.ord = i; });
  const cabecalhos = [...t.querySelectorAll('th')];
  let coluna = -1, sentido = 1;
  const valor = (linha, c) => {
    if (c === 0) return Number(linha.dataset.ord);
    const m = linha.cells[c].textContent.replace(/\./g, '').match(/^-?\d+(?:,\d+)?/);
    return m ? parseFloat(m[0].replace(',', '.')) : null;
  };
  cabecalhos.forEach((th, c) => {
    const botao = el('button', th.textContent);
    botao.type = 'button';
    th.replaceChildren(botao);
    th.setAttribute('aria-sort', 'none');
    botao.addEventListener('click', () => {
      sentido = coluna === c ? -sentido : 1;
      coluna = c;
      tbody.replaceChildren(...[...tbody.rows].sort((a, b) => {
        const va = valor(a, c), vb = valor(b, c);
        if (va === null || vb === null) return (va === null) - (vb === null);
        return (va - vb) * sentido;
      }));
      cabecalhos.forEach((t2, i) => t2.setAttribute('aria-sort', i !== coluna ? 'none' : sentido > 0 ? 'ascending' : 'descending'));
    });
  });
}

// ---------- Gráficos ----------
// Os gráficos se redesenham com a largura do espaço, então o texto mantém o tamanho legível no celular.
let observadores = [];
function ligar(alvo, desenhar) {
  let primeira = true, ultima = 0;
  const pintarGrafico = w => {
    if (!(w >= 160) || w === ultima) return; // NaN (elemento ainda fora da página) também sai
    ultima = w;
    alvo.innerHTML = desenhar(w);
    alvo.classList.toggle('anima', primeira && !REDUZIR); // barras crescem só na primeira vez
    primeira = false;
  };
  const medir = () => {
    const estilo = getComputedStyle(alvo);
    pintarGrafico(Math.floor(alvo.clientWidth - parseFloat(estilo.paddingLeft) - parseFloat(estilo.paddingRight)));
  };
  medir();                // já na página
  queueMicrotask(medir);  // ainda solta: mede logo depois de entrar na página, sem esperar o observador
  const obs = new ResizeObserver(([entrada]) => pintarGrafico(Math.floor(entrada.contentRect.width)));
  obs.observe(alvo);
  observadores.push(obs);
}
const limparObservadores = () => { observadores.forEach(o => o.disconnect()); observadores = []; };

const MES_NOMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
const MES_CURTO = MES_NOMES.map(m => m.slice(0, 3));

// Climograma: barras para a chuva média de cada mês (mm, à esquerda) e linha para a temperatura média (°C, à direita).
function svgClima(j, W) {
  const H = Math.round(Math.min(460, Math.max(250, W * 0.42))), e = {l: 52, r: 44, t: 34, b: 30};
  const pw = W - e.l - e.r, ph = H - e.t - e.b, base = e.t + ph;
  const P = j.clima_chuva, T = j.clima_temperatura;
  const pmax = Math.max(100, Math.ceil(Math.max(...P) / 50) * 50);
  const tmin = Math.floor((Math.min(...T) - 2) / 5) * 5, tmax = Math.ceil((Math.max(...T) + 2) / 5) * 5;
  const x = i => e.l + (i + 0.5) * pw / 12;
  const yp = v => base - v / pmax * ph;
  const yt = v => base - (v - tmin) / (tmax - tmin) * ph;
  const bw = pw / 12 * 0.62;
  const rotulos = W >= 520 ? MES_CURTO : MES_NOMES.map(m => m[0]);
  const resumo = `Climograma. Chuva média mensal de ${numero(Math.min(...P), 0)} a ${numero(Math.max(...P), 0)} mm. ` +
    `Temperatura média mensal de ${numero(Math.min(...T), 1)} a ${numero(Math.max(...T), 1)} °C. Os valores estão na tabela abaixo.`;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${resumo}">`;
  s += `<text class="t-chuva" x="0" y="14">mm/mês</text><text class="t-calor" x="${W}" y="14" text-anchor="end">°C</text>`;
  for (const v of [0, pmax / 2, pmax]) s += `<line x1="${e.l}" x2="${W - e.r}" y1="${yp(v)}" y2="${yp(v)}" stroke="${GRADE}"/>`
    + `<text x="${e.l - 8}" y="${yp(v) + 4}" text-anchor="end">${v}</text>`;
  for (let v = tmin; v <= tmax; v += 5) s += `<text x="${W - e.r + 8}" y="${yt(v) + 4}">${v}</text>`;
  P.forEach((v, i) => { s += `<rect class="barra" x="${x(i) - bw / 2}" y="${yp(v)}" width="${bw}" height="${base - yp(v)}" fill="${CHUVA}"/>`; });
  s += `<polyline fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round" points="${T.map((v, i) => `${x(i)},${yt(v)}`).join(' ')}"/>`
    + `<polyline fill="none" stroke="${CALOR}" stroke-width="3" stroke-linejoin="round" points="${T.map((v, i) => `${x(i)},${yt(v)}`).join(' ')}"/>`;
  T.forEach((v, i) => { s += `<circle cx="${x(i)}" cy="${yt(v)}" r="4" fill="${CALOR}" stroke="#fff" stroke-width="1.5"/>`; });
  rotulos.forEach((m, i) => { s += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${m}</text>`; });
  return s + '</svg>';
}

// Tendência: série anual com a reta ajustada tracejada.
function svgTendencia(titulo, pontos, casas, cor, [a, b], W) {
  const H = Math.round(Math.min(230, Math.max(160, W * 0.4))), e = {l: 56, r: 10, t: 12, b: 26};
  const pw = W - e.l - e.r, ph = H - e.t - e.b;
  const x0 = pontos[0][0], x1 = pontos[pontos.length - 1][0];
  const ys = pontos.map(p => p[1]), pad = (Math.max(...ys) - Math.min(...ys)) * 0.1 || 1;
  const lo = Math.min(...ys) - pad, hi = Math.max(...ys) + pad;
  const x = v => e.l + (v - x0) / Math.max(1, x1 - x0) * pw;
  const y = v => e.t + ph - (v - lo) / (hi - lo) * ph;
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${titulo} de ${x0} a ${x1}, com linha de tendência. Os valores estão na tabela abaixo.">`;
  for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${e.l}" x2="${W - e.r}" y1="${y(v)}" y2="${y(v)}" stroke="${GRADE}"/>`
    + `<text x="${e.l - 8}" y="${y(v) + 4}" text-anchor="end">${numero(v, casas)}</text>`;
  s += `<text x="${e.l}" y="${H - 6}">${x0}</text><text x="${W - e.r}" y="${H - 6}" text-anchor="end">${x1}</text>`;
  s += `<polyline fill="none" stroke="${cor}" stroke-width="2" stroke-linejoin="round" points="${pontos.map(p => `${x(p[0])},${y(p[1])}`).join(' ')}"/>`;
  s += `<line x1="${x(x0)}" x2="${x(x1)}" y1="${y(a + b * x0)}" y2="${y(a + b * x1)}" stroke="${TINTA}" stroke-width="2" stroke-dasharray="6 4"/>`;
  s += pontos.map(p => `<circle cx="${x(p[0])}" cy="${y(p[1])}" r="3" fill="${cor}" stroke="#fff" stroke-width="1"/>`).join('') + '</svg>';
  return s;
}
function blocoTendencia(titulo, pontos, casas, cor, unidade, par) {
  const caixa = el('div', '', 'tend-bloco');
  const p = el('p', `${titulo}: `);
  p.append(el('span', `${comSinal(par[1] * 10, casas)} ${unidade} por década`, 'valor'));
  const host = el('div', '', 'grafico');
  caixa.append(p, host);
  if (pontos.length) ligar(host, w => svgTendencia(titulo, pontos, casas, cor, par, w));
  else host.textContent = 'Esta série não tem ano completo.';
  return caixa;
}

// ---------- Estação ----------
const GRUPOS = {A: 'tropical', B: 'árido', C: 'temperado', D: 'continental', E: 'polar'};

function fatos(j) {
  const alt = j.koppen_alternativas;
  const kop = alt.length ? [j.koppen, ...alt].join(' ou ') : `${j.koppen} (clima ${GRUPOS[j.koppen[0]]})`;
  const itens = [
    ['Tamanho da série', `${numero(j.anos, 1)} anos`, ''],
    ['Dias estimados pelo modelo', `${numero(j.estimados_pct, 1)}%`, ''],
    ['Altitude', j.altitude == null ? 'Sem informação' : `${numero(j.altitude, 0)} m`, ''],
    ['Classificação de Köppen', kop, ''],
    ['Chuva média', `${numero(j.chuva_mensal, 1)} mm/mês`, 'fato-chuva'],
    ['Temperatura média', `${numero(j.temperatura_mensal, 1)} °C`, 'fato-calor'],
  ];
  $('est-fatos').replaceChildren(...itens.map(([nome, valor, classe]) => {
    const d = el('div', '', classe);
    d.append(el('dt', nome), el('dd', valor));
    return d;
  }));
  const aviso = $('est-aviso');
  aviso.hidden = !alt.length;
  if (alt.length) {
    // Divisa: a classe muda com ±1 °C no mês mais frio ou ±5% na chuva. Os valores mostram quão perto está.
    const minT = Math.min(...j.clima_temperatura), minP = Math.min(...j.clima_chuva);
    aviso.textContent = `A estação fica na divisa entre classes. O mês mais frio tem média de ${numero(minT, 1)} °C e o mês mais seco, ${numero(minP, 0)} mm. ` +
      `Com 1 °C a mais ou a menos, ou 5% de chuva a mais ou a menos, a classe pode ser ${alt.join(' ou ')}. A principal é ${j.koppen}.`;
  }
}

let recJanela = null, recCompleta = null, ultimoPedido = 0, recEstacao = null;
let ultimoAberto = null;

function mostrarEstacao(j) {
  ultimoAberto = j.id;
  alternar(false);
  limparObservadores();
  document.title = `${nomeDe(j)} · Atlas Climático`;
  $('est-titulo').textContent = nomeDe(j);
  $('est-sub').textContent = `Estação ${tipoRede(j).toLowerCase()}, código ${j.codigo}. Série completa de ${periodo(j)}.`;
  fatos(j);
  ligar($('clima-svg'), w => svgClima(j, w));
  $('clima-tab').replaceChildren(tabela('Médias mensais de chuva e temperatura', ['Mês', 'Chuva média (mm)', 'Temperatura média (°C)'],
    MES_NOMES.map((m, i) => [m, numero(j.clima_chuva[i], 1), numero(j.clima_temperatura[i], 1)])));
  const anual = j.serie_anual;
  $('tendencia').replaceChildren(
    blocoTendencia('Chuva por ano', anual.map(p => [p[0], p[1]]), 1, CHUVA, 'mm/ano', j.tendencia.chuva),
    blocoTendencia('Temperatura média por ano', anual.map(p => [p[0], p[2]]), 2, CALOR, '°C', j.tendencia.temp));
  $('tend-tab').replaceChildren(tabela('Chuva e temperatura média de cada ano completo', ['Ano', 'Chuva (mm)', 'Temperatura média (°C)'],
    anual.map(p => [String(p[0]), numero(p[1], 1), numero(p[2], 2)]), true));
  recEstacao = j;
  atualizarRecordes();
  window.scrollTo(0, 0);
  $('est-titulo').focus({preventScroll: true});
}

// ---------- Recordes ----------
// Dia do ano: recorde de cada dia entre os anos; mês: média mensal de temperatura e total mensal de chuva, mais alta
// e mais baixa; ano: média e total de cada ano. Dentro da série e no histórico completo, lado a lado.
const RECORDES_GERAL = [
  ['tmax', 'Maior temperatura máxima diária', '°C'], ['tmin', 'Menor temperatura mínima diária', '°C'],
  ['chuva', 'Maior chuva em um dia', 'mm'],
  ['tmed_mes_alta', 'Maior média mensal de temperatura', '°C'], ['tmed_mes_baixa', 'Menor média mensal de temperatura', '°C'],
  ['chuva_mes_alta', 'Maior total mensal de chuva', 'mm'], ['chuva_mes_baixa', 'Menor total mensal de chuva', 'mm'],
  ['tmed_ano_alta', 'Maior média anual de temperatura', '°C'], ['tmed_ano_baixa', 'Menor média anual de temperatura', '°C'],
  ['chuva_ano_alta', 'Maior total anual de chuva', 'mm'], ['chuva_ano_baixa', 'Menor total anual de chuva', 'mm'],
];
// Arquivos estáticos gerados por pipeline/exportar_site.py: j<id da janela> e e<id da estação>.
const buscarRecordes = async arquivo => (await pedir(`api/recordes/${arquivo}.json`)).grupos;

async function atualizarRecordes() {
  const j = recEstacao;
  const pedido = ++ultimoPedido;
  $('rec-janela-titulo').textContent = `Nesta série, de ${periodo(j)}`;
  try {
    const [janela, completa] = await Promise.all([
      buscarRecordes('j' + j.id),
      buscarRecordes('e' + j.estacao_id)]);
    if (pedido !== ultimoPedido) return;
    recJanela = janela;
    recCompleta = completa;
    $('rec-erro').textContent = '';
  } catch (erro) {
    if (pedido !== ultimoPedido) return;
    recJanela = recCompleta = null;
    $('rec-erro').textContent = erro.message;
  }
  desenharRecordes();
}

// 'AAAA-MM-DD' vira dd/mm/aaaa, 'AAAA-MM' vira mm/aaaa, 'AAAA' fica.
const rotuloData = r => r.length === 10 ? data(r) : r.length === 7 ? `${r.slice(5)}/${r.slice(0, 4)}` : r;
const registro = (par, casas) => par ? `${numero(par[0], casas)} (${rotuloData(par[1])})` : '—';

function tabelaRecordes(grupo, g, legenda) {
  if (!g) return el('p', 'Sem recordes para mostrar.');
  if (grupo === 'geral') {
    return tabela(legenda, ['Recorde', 'Valor (data)'], RECORDES_GERAL.map(([campo, nome, unidade]) => {
      const par = g.geral[campo];
      return [nome, par ? `${numero(par[0], 1)} ${unidade} (${rotuloData(par[1])})` : '—'];
    }));
  }
  if (grupo === 'dia') {
    return tabela(legenda, ['Dia', 'Temp. máx. (°C)', 'Temp. mín. (°C)', 'Maior chuva em 1 dia (mm)'],
      g.dia.map(r => [`${r.rotulo.slice(3)}/${r.rotulo.slice(0, 2)}`, registro(r.tmax, 1), registro(r.tmin, 1), registro(r.chuva, 1)]), true);
  }
  if (grupo === 'mes') {
    return tabela(legenda, ['Mês', 'Média mais alta (°C)', 'Média mais baixa (°C)', 'Chuva mensal mais alta (mm)', 'Chuva mensal mais baixa (mm)'],
      g.mes.map(r => [MES_NOMES[Number(r.rotulo) - 1], registro(r.tmed_mes_alta, 1), registro(r.tmed_mes_baixa, 1),
        registro(r.chuva_mes_alta, 1), registro(r.chuva_mes_baixa, 1)]), true);
  }
  return tabela(legenda, ['Ano', 'Temp. média (°C)', 'Chuva total (mm)'], g.ano.map(r => [r.rotulo, numero(r.tmed, 1), numero(r.chuva, 1)]), true);
}

function desenharRecordes() {
  const grupo = document.querySelector('input[name="rec"]:checked').value;
  $('rec-janela').replaceChildren(tabelaRecordes(grupo, recJanela, 'Recordes dentro da série'));
  $('rec-completa').replaceChildren(tabelaRecordes(grupo, recCompleta, 'Recordes em todo o histórico da estação'));
}
$('rec-grupo').addEventListener('change', desenharRecordes);

// ---------- Mapa e lista ----------
$('leg-classes').replaceChildren(...CLASSES.map(c => {
  const li = el('li'), marca = el('i');
  marca.style.background = c.cor;
  marca.setAttribute('aria-hidden', 'true');
  li.append(marca, c.nome);
  return li;
}));
// Mapa MapLibre preso à América do Sul, com o fundo "Ruas" do OpenFreeMap (gratuito, sem chave de API).
// Os pontos são uma camada GeoJSON.
const mapa = new maplibregl.Map({container: 'map', style: 'https://tiles.openfreemap.org/styles/liberty',
  center: [-58, -16], zoom: 3.2, minZoom: 3, maxZoom: 8,
  maxBounds: [[-95, -60], [-15, 16]], attributionControl: {compact: true}});
mapa.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-left');
const caixaPopup = new maplibregl.Popup({maxWidth: '320px', offset: 12});
let estiloPronto = false, dadosGeo = {type: 'FeatureCollection', features: []};
const grupoPorRep = new Map(); // id da série representante -> séries da estação
const repDe = new Map();       // id de qualquer série -> id do representante

function desenharCamadas() {
  estiloPronto = true;
  if (mapa.getSource('estacoes')) return;
  mapa.addSource('estacoes', {type: 'geojson', data: dadosGeo, promoteId: 'id'});
  const realce = ['boolean', ['feature-state', 'realce'], false];
  // Tamanho fixo na escala do mapa: o raio dobra a cada nível de zoom, então o ponto cobre sempre a mesma área
  // (cerca de 20 km de raio) a partir do zoom 4. Na vista do continente (zoom 3) há um piso de 3,5 px para o
  // ponto não sumir. Em px: 4 no zoom 4, 64 no zoom 8. O realce da lista aumenta 40%.
  const raio = fator => ['interpolate', ['exponential', 2], ['zoom'],
    3, ['*', fator, ['case', realce, 4.9, 3.5]], 4, ['*', fator, ['case', realce, 5.6, 4]], 9, ['*', fator, ['case', realce, 179, 128]]];
  // Anel fino = estação com mais de uma série.
  mapa.addLayer({id: 'aneis', type: 'circle', source: 'estacoes', filter: ['get', 'multi'],
    paint: {'circle-radius': raio(1.55), 'circle-opacity': 0, 'circle-stroke-color': TINTA, 'circle-stroke-width': 1.5}});
  mapa.addLayer({id: 'pontos', type: 'circle', source: 'estacoes', paint: {
    'circle-radius': raio(1), 'circle-color': ['get', 'cor'], 'circle-opacity': 1,
    'circle-stroke-color': TINTA, 'circle-stroke-width': ['case', realce, 2.5, 1]}});
}
mapa.on('style.load', desenharCamadas);

// Seleção pelo mapa: o alvo de clique é maior que o ponto (10 px de folga, vale o mais próximo), o ponto sob o
// mouse é realçado com uma dica de nome, e com mouse um clique abre a série direto quando a estação só tem uma.
// Em telas de toque o primeiro toque abre o popup, para não navegar sem querer.
const FOLGA = 10;
function pontoEm(e) {
  if (!mapa.getLayer('pontos')) return;
  const {x, y} = e.point;
  let melhor, menor = Infinity;
  for (const f of mapa.queryRenderedFeatures([[x - FOLGA, y - FOLGA], [x + FOLGA, y + FOLGA]], {layers: ['pontos']})) {
    const p = mapa.project(f.geometry.coordinates), d = (p.x - x) ** 2 + (p.y - y) ** 2;
    if (d < menor) { menor = d; melhor = f; }
  }
  return melhor;
}
const dica = new maplibregl.Popup({closeButton: false, closeOnClick: false, closeOnMove: false, offset: 14, className: 'dica'});
let sobre = null;
const realceMapa = (id, ligado) => { if (id != null && mapa.getSource('estacoes')) mapa.setFeatureState({source: 'estacoes', id}, {realce: ligado}); };
function sair() { realceMapa(sobre, false); sobre = null; dica.remove(); mapa.getCanvas().style.cursor = ''; }
mapa.on('mousemove', e => {
  const f = pontoEm(e), id = f ? f.properties.id : null;
  mapa.getCanvas().style.cursor = f ? 'pointer' : '';
  if (id === sobre) return;
  realceMapa(sobre, false);
  sobre = id;
  realceMapa(id, true);
  if (!f) return dica.remove();
  const g = grupoPorRep.get(id);
  dica.setLngLat(f.geometry.coordinates).setText(nomeDe(g[0]) + (g.length > 1 ? `, ${g.length} séries` : `, ${numero(g[0].anos, 1)} anos`)).addTo(mapa);
});
mapa.getCanvas().addEventListener('mouseleave', sair);
mapa.on('click', e => {
  const f = pontoEm(e);
  if (!f) return;
  const g = grupoPorRep.get(f.properties.id);
  sair();
  if (g.length === 1 && !TOQUE.matches) { location.hash = `#/serie/${g[0].id}`; return; }
  caixaPopup.setLngLat(f.geometry.coordinates).setDOMContent(popup(g)).addTo(mapa);
  destacarItem(f.properties.id);
});
const colador = new Intl.Collator('pt-BR');
const ORDENS = {
  nome: (a, b) => colador.compare(nomeDe(a), nomeDe(b)) || a.inicio.localeCompare(b.inicio),
  anos: (a, b) => b.anos - a.anos,
  chuva: (a, b) => b.chuva_mensal - a.chuva_mensal,
  temperatura: (a, b) => b.temperatura_mensal - a.temperatura_mensal,
};
let todas = [], visiveis = [];
const contagem = new Map(); // estacao_id -> número de séries

// Uma estação pode ter várias séries de 10 anos ou mais: o popup lista todas.
function popup(g) {
  const caixa = document.createElement('div');
  caixa.append(el('strong', nomeDe(g[0])), el('div', `${tipoRede(g[0])}, código ${g[0].codigo}`));
  if (g.length > 1) caixa.append(el('div', `${g.length} séries com 10 anos ou mais`));
  for (const j of g) {
    const bloco = el('div', '', 'popup-trecho');
    bloco.append(el('div', `${periodo(j)}, ${numero(j.anos, 1)} anos`),
      el('div', `Chuva ${numero(j.chuva_mensal, 1)} mm/mês, temperatura ${numero(j.temperatura_mensal, 1)} °C`));
    if (j.estimados_pct > 0) bloco.append(el('div', `${numero(j.estimados_pct, 1)}% dos dias estimados`));
    const ver = el('a', g.length > 1 ? `Ver série de ${data(j.inicio).slice(3)} a ${data(j.fim).slice(3)}` : 'Ver estação');
    ver.href = `#/serie/${j.id}`;
    bloco.append(ver);
    caixa.append(bloco);
  }
  return caixa;
}

// Desenha mapa e lista. Um ponto por estação, no lugar da série mais longa. Anel = mais de uma série.
function pintar() {
  caixaPopup.remove();
  sair();
  grupoPorRep.clear();
  repDe.clear();
  const grupos = new Map();
  for (const j of visiveis) grupos.set(j.estacao_id, [...(grupos.get(j.estacao_id) || []), j]);
  const features = [];
  for (const g of grupos.values()) {
    const rep = g.reduce((a, b) => (b.anos > a.anos ? b : a));
    grupoPorRep.set(rep.id, g);
    g.forEach(j => repDe.set(j.id, rep.id));
    features.push({type: 'Feature', geometry: {type: 'Point', coordinates: [rep.lon, rep.lat]},
      properties: {id: rep.id, cor: classeDe(rep.anos).cor, multi: contagem.get(rep.estacao_id) > 1}});
  }
  dadosGeo = {type: 'FeatureCollection', features};
  const fonte = mapa.getSource('estacoes');
  if (fonte) fonte.setData(dadosGeo); else if (estiloPronto) desenharCamadas();

  $('lista').replaceChildren(...visiveis.map(j => {
    const a = el('a', '', 'item');
    a.href = `#/serie/${j.id}`;
    a.dataset.id = j.id;
    const ponto = el('span', '', 'ponto');
    ponto.style.background = classeDe(j.anos).cor;
    ponto.setAttribute('aria-hidden', 'true');
    const medidas = el('span', '', 'item-medidas');
    medidas.append(el('span', `${numero(j.chuva_mensal, 1)} mm/mês`, 'm-chuva'), el('span', `${numero(j.temperatura_mensal, 1)} °C`, 'm-calor'));
    const corpo = el('span');
    const n = contagem.get(j.estacao_id);
    const irmaos = todas.filter(x => x.estacao_id === j.estacao_id);
    const serie = n > 1 ? `, série ${irmaos.findIndex(x => x.id === j.id) + 1} de ${n}` : '';
    corpo.append(el('span', nomeDe(j), 'item-nome'), el('span', `${tipoRede(j)}, ${periodo(j)}, ${numero(j.anos, 1)} anos${serie}`, 'item-meta'), medidas);
    a.append(ponto, corpo);
    const li = document.createElement('li');
    li.append(a);
    return li;
  }));
}

function aplicar(ajustar) {
  const rede = $('rede').value, busca = semAcento($('busca').value.trim());
  visiveis = todas
    .filter(j => (rede === 'todas' || j.tipo === rede) && (!busca || semAcento(`${nomeDe(j)} ${j.codigo}`).includes(busca)))
    .sort(ORDENS[$('ordem').value]);
  pintar();
  const estacoes = new Set(visiveis.map(j => j.codigo)).size;
  $('resumo').textContent = visiveis.length
    ? `${visiveis.length} ${visiveis.length === 1 ? 'série' : 'séries'} em ${estacoes} ${estacoes === 1 ? 'estação' : 'estações'}.`
    : 'Nenhuma série encontrada com esta busca.';
  $('limpar').hidden = visiveis.length > 0;
  if (ajustar && visiveis.length) {
    mapa.resize(); // o tamanho pode ter mudado desde que o mapa foi criado
    const limites = new maplibregl.LngLatBounds();
    visiveis.forEach(j => limites.extend([j.lon, j.lat]));
    mapa.fitBounds(limites, {padding: 40, maxZoom: 7, duration: REDUZIR ? 0 : 600});
  }
}

// Clicar num ponto do mapa mostra a mesma estação na lista (só quando a lista fica ao lado do mapa).
function destacarItem(id) {
  const lista = $('lista');
  lista.querySelector('.no-mapa')?.classList.remove('no-mapa');
  const a = lista.querySelector(`.item[data-id="${id}"]`);
  if (!a) return;
  a.classList.add('no-mapa');
  if (DESKTOP.matches) a.scrollIntoView({block: 'nearest'});
}
// Passar o mouse ou o foco numa linha da lista aumenta o ponto no mapa.
function realcar(e, ligado) {
  const a = e.target.closest('.item');
  const id = a && repDe.get(Number(a.dataset.id));
  if (id != null && mapa.getSource('estacoes')) mapa.setFeatureState({source: 'estacoes', id}, {realce: ligado});
}
const listaEl = $('lista');
listaEl.addEventListener('mouseover', e => realcar(e, true));
listaEl.addEventListener('mouseout', e => realcar(e, false));
listaEl.addEventListener('focusin', e => realcar(e, true));
listaEl.addEventListener('focusout', e => realcar(e, false));

// ---------- Vistas ----------
function alternar(lista) {
  $('vista-lista').hidden = !lista;
  $('vista-estacao').hidden = lista;
  if (lista) mapa.resize();
}

let rotaAberta = false; // a 1ª abertura da página não faz fade
function rota() {
  if (!todas.length) return;
  if (location.hash && !location.hash.startsWith('#/')) return; // âncora da página (índice do cabeçalho), não é rota
  const m = location.hash.match(/^#\/serie\/(\d+)$/);
  const j = m && todas.find(x => x.id === Number(m[1]));
  if (m && !j) return location.replace('#/'); // série que não existe
  // A troca de vista faz um fade curto onde o navegador permite (e o usuário não pediu menos movimento).
  const animar = rotaAberta && document.startViewTransition && !REDUZIR && !document.hidden;
  rotaAberta = true;
  const trocar = f => (animar ? document.startViewTransition(f) : f());
  if (j) return trocar(() => mostrarEstacao(j));
  trocar(() => {
    limparObservadores();
    alternar(true);
    document.title = 'Atlas Climático';
    const volta = ultimoAberto && $('lista').querySelector(`.item[data-id="${ultimoAberto}"]`);
    if (volta) { volta.scrollIntoView({block: 'nearest'}); volta.focus({preventScroll: true}); }
    else window.scrollTo({top: 0, behavior: REDUZIR ? 'auto' : 'smooth'}); // "Atlas" no índice leva ao topo
    ultimoAberto = null;
  });
}

async function carregar() {
  $('erro').hidden = true;
  $('resumo').textContent = 'Carregando estações…';
  try {
    todas = (await pedir('api/janelas.json')).janelas;
  } catch (erro) {
    $('resumo').textContent = '';
    $('lista').replaceChildren(); // some o esqueleto: o erro e o botão explicam o que fazer
    $('erro-texto').textContent = erro.message;
    $('erro').hidden = false;
    return;
  }
  contagem.clear();
  for (const j of todas) contagem.set(j.estacao_id, (contagem.get(j.estacao_id) || 0) + 1);
  const total = $('sobre-total');
  total.textContent = `Hoje o atlas reúne ${todas.length} séries de ${contagem.size} estações.`;
  total.hidden = false;
  aplicar(true);
  rota();
}

let espera;
$('busca').addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(() => aplicar(true), 250); });
$('rede').addEventListener('change', () => aplicar(true));
$('limpar').addEventListener('click', () => { $('busca').value = ''; $('rede').value = 'todas'; aplicar(true); $('busca').focus(); });
$('ordem').addEventListener('change', () => aplicar(false));
$('tentar').addEventListener('click', carregar);
addEventListener('hashchange', rota);
carregar();
