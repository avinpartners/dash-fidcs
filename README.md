# Dash FIDCs

Painel dos FIDCs do mercado brasileiro, feito na mesma estrutura do **Dash Fundos** (Ricardo): servidor Python
(FastAPI) com banco PostgreSQL, tarefas automáticas que baixam os dados da CVM todo dia e a mesma interface (React,
cores e logo AVIN, tema claro/escuro, busca com Ctrl+K). Roda no notebook e a equipe abre pelo navegador.

Todos os dados vêm de fontes públicas e gratuitas da CVM (detalhes em **Mais › Metodologia** dentro do app):

- **Informe Mensal FIDC**: PL, carteira por segmento, inadimplência por faixa de atraso, PDD, subordinação, séries de
  cotas, rentabilidade, cotistas por tipo de investidor, captações/resgates/amortizações, liquidez, prazo, rating SCR e
  os maiores cedentes. Últimos 24 meses.
- **Cadastro de fundos e classes (RCVM 175)**: gestor, administrador, custodiante, auditor, situação (ativo, em
  liquidação, cancelado), constituição, adaptação à RCVM 175, público-alvo.

## Telas

- **Início:** o mercado na competência mais recente (nº de FIDCs, PL, captação líquida, cotistas, inadimplência,
  subordinação), histórico mês a mês, PL por segmento, maiores gestoras, quem investe, fundos novos e os que entraram
  em liquidação.
- **FIDCs:** todos os fundos/classes numa tabela com busca, filtros (segmento, subsegmento, gestor, administrador,
  custodiante, tipo de alocador, situação, estrutura, condomínio, PL mínimo), ordenação e exportação CSV. O endereço da
  página guarda os filtros, então dá para mandar o link de uma lista filtrada.
- **Página do FIDC:** identificação completa, indicadores e gráficos do histórico (PL e cotistas, estrutura de cotas,
  inadimplência/PDD/subordinação, rentabilidade, fluxos), carteira por segmento, prazo, liquidez, rating, cotistas por
  tipo, séries de cotas, maiores cedentes, outras classes do fundo e outros FIDCs da gestora.
- **Gestoras, Administradores, Custodiantes (em Mais):** cada um com seus FIDCs somados.
- **Cedentes:** CNPJs informados como maiores cedentes e em quais FIDCs aparecem (bom para prospecção).
- **Status dos dados:** quando cada tarefa rodou, botão **Atualizar agora**, logs e erros.

## Iniciar e parar

Na pasta `Dash FIDCs`:

- **Iniciar:** dois cliques em **`Iniciar.cmd`**. O painel abre no navegador em http://localhost:8081.
- **Parar:** dois cliques em **`Parar.cmd`**.

Nada disso precisa de administrador. Porta **8081** e banco na porta **5434**, para poder rodar no mesmo
computador que o Dash Fundos (8080/5433) sem conflito.

### Antes da primeira vez

1. **Python 3.12** instalado para o seu usuário: python.org › Downloads › Windows, opção *Install for me only*. Se o
   Iniciar.cmd disser que não achou o Python, é isso.
2. Na primeira vez o `Iniciar.cmd` prepara o computador (5 a 10 minutos): cria o ambiente Python, baixa o PostgreSQL 16
   (cerca de 370 MB, do site da EnterpriseDB) para `%LOCALAPPDATA%\DashFIDCs` e grava o arquivo `.env`.
3. Depois começa a primeira carga: o cadastro da CVM e 24 arquivos mensais (alguns MB cada). Leva de 10 a 30 minutos;
   acompanhe em **Status dos dados**. O painel já pode ser usado enquanto isso.

Se algum passo falhar, a janela fica aberta com a mensagem em português. Os casos mais comuns: Python não instalado;
a rede bloqueando `dados.cvm.gov.br` ou o download do PostgreSQL; o App Control da empresa bloqueando um programa
(a mensagem pede um print para mandar à TI).

### Atualização automática

| Quando | O quê |
|---|---|
| Todo dia às 08:00 | Cadastro de fundos e classes da CVM |
| Todo dia às 08:15 | Informe mensal FIDC (só baixa de novo o que a CVM mudou) |
| Toda meia-noite | Backup do banco em `backups\` (guarda os 14 últimos) |

Se o notebook estiver desligado no horário, as tarefas atrasadas rodam quando o painel for iniciado. O botão
**Atualizar agora** em Status dos dados roda tudo na hora.

Configurações opcionais no `.env`: `FIDC_HISTORY_MONTHS` (meses lidos, padrão 24), `APP_PASSCODE` (senha compartilhada
para abrir o painel).

## Abrir de outro computador

Igual ao Dash Fundos: a TI precisa liberar a porta, agora a **8081**:

```
New-NetFirewallRule -DisplayName "Dash FIDCs" -Direction Inbound -Protocol TCP -LocalPort 8081 -Action Allow -Profile Domain,Private
```

Depois, no `.env`, troque `APP_HOST=127.0.0.1` por `APP_HOST=0.0.0.0`, rode `Parar.cmd` e `Iniciar.cmd`. Os colegas
abrem `http://<nome-do-notebook>:8081`.

## Versão online (sem depender do notebook)

O arquivo `.github/workflows/publicar.yml` faz o GitHub, de graça, rodar o painel sozinho: todo dia útil às
08:37 ele baixa os dados da CVM, gera um arquivo por tela (`backend/app/export_static.py`) e publica o site no
GitHub Pages. O link abre de qualquer lugar, para qualquer pessoa que o tiver. Na versão online a busca roda no
navegador, e não há botão **Atualizar agora**: para atualizar fora do horário, use **Actions › Publicar Dash FIDCs ›
Run workflow** no GitHub. Se a CVM falhar num dia, a publicação para e o site do dia anterior continua no ar.

## Estrutura do código

- `backend/app/ingest/cvm_fidc.py`: leitura dos arquivos da CVM (as duas tarefas).
- `backend/app/api/fidcs.py`: as consultas de cada tela.
- `backend/db/schema.sql`: tabelas (`fidcs`, `fidc_mensal`, `fidc_series`, `fidc_cedentes`, `cadastro_cvm`).
- `backend/app/core`, `backend/app/jobs`, `scripts/`: estrutura herdada do Dash Fundos (downloads educados com cache,
  agendador com recuperação de tarefas atrasadas, backup, scripts de instalação sem administrador).
- `frontend/`: interface (React + ECharts). `frontend/dist` já vem pronto; só é preciso Node para mudar a interface
  (`npm install` e `npm run build` dentro de `frontend`).

## O que não foi testado

O código foi escrito e testado num ambiente que não alcança o site da CVM. As leituras e as telas foram testadas com
os arquivos de janeiro de 2026 baixados manualmente, mas os endereços de download e os scripts de Windows só serão
testados de verdade na primeira execução no notebook. Se algo falhar, a página **Status dos dados** mostra o erro.
