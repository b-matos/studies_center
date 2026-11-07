# Fontes primárias por tipo de evento

Para cada tipo de evento em `eventos.csv`, o `historiador` consulta primeiro estas fontes
primárias. Fontes secundárias (Lusa, Público, Expresso, Observador, RTP, Reuters, etc.) só
servem de contexto ou quando a fonte primária não está acessível, e ficam marcadas como tal.

| Tipo | Fonte primária | Janela plausível até ao efeito |
| --- | --- | --- |
| Lei ou decreto-lei | [Diário da República Eletrónico](https://diariodarepublica.pt) | 0–5 anos (depende da entrada em vigor e implementação) |
| Orçamento do Estado | [Diário da República](https://diariodarepublica.pt) · [Portal do Orçamento, DGO](https://www.dgo.gov.pt) | 0–2 anos |
| Mudança de governo | [gov.pt](https://www.gov.pt) · [Presidência da República](https://www.presidencia.pt) | 0–3 anos |
| Eleição | [Comissão Nacional de Eleições (CNE)](https://www.cne.pt) | imediato a 2 anos (tomada de posse + legislação) |
| Diretiva ou regulamento europeu | [EUR-Lex](https://eur-lex.europa.eu) | 0–3 anos (transposição) |
| Programa ou plano nacional | gov.pt · ministério responsável (ex.: [SNS](https://www.sns.gov.pt), [DGS](https://www.dgs.pt)) | 1–10 anos |
| Crise económica ou intervenção externa | [Banco de Portugal](https://www.bportugal.pt) · [FMI](https://www.imf.org) · [Comissão Europeia](https://ec.europa.eu) | imediato a 5 anos |
| Pandemia ou crise sanitária | [DGS](https://www.dgs.pt) · [OMS](https://www.who.int) | 0–1 ano |
| Catástrofe natural ou climática | [ANEPC](https://www.prociv.pt) · [IPMA](https://www.ipma.pt) | imediato a 2 anos |
| Greve ou conflito laboral | [DGERT](https://www.dgert.gov.pt) · comunicados sindicais/patronais oficiais | imediato a 1 ano |
| Evento internacional relevante | organismo internacional competente (ONU, OMS, UE, NATO, etc.) | depende do evento |

Regras:
- Um evento só entra no catálogo com `fonte_primaria_url` preenchido. Se não existir fonte
  primária acessível, regista-se o motivo e usa-se fonte secundária com `verificado = não` até
  ser confirmado.
- A janela "plausível" justifica a procura do `historiador`, não um limite rígido — regista-se
  sempre a justificação na ligação em `ligacoes_eventos.csv`.
