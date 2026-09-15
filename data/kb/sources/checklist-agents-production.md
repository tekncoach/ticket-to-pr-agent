# Ce qu'exige un système agentique de production — la checklist Rubicon

besoin → stratégie → ROI → conception → extensibilité → orchestration → supervision → test → cycle de vie → sécurité.

> Revisit : quand une autre annonce détaille mieux · Dernière retouche : 2026-08-28

**Ce que c'est.** La section « What we are looking for » de l'annonce [AI / Agentic Systems Engineer chez Rubicon](https://www.linkedin.com/jobs/view/4459388003/), publiée le 26/08/2026, recopiée mot pour mot. Onze domaines, du modèle jusqu'au réseau.

**Pourquoi elle est gardée.** C'est la description la plus complète rencontrée à ce jour de ce qu'il faut tenir pour faire tourner des agents en entreprise, et pas une démo. Elle sert de carte du terrain — à quoi se former, et quel vocabulaire employer face à une équipe qui en est là.

⚠️ **Elle ne sert pas à s'auto-évaluer.** Onze domaines écrits par une équipe de quatre personnes, c'est la liste des besoins de toute la boîte, pas le profil d'une personne. L'annonce le dit elle-même, deux lignes plus bas : *« You do not need to be an expert in every area above. »*

---

## Verbatim — What we are looking for

We are primarily looking for an exceptional software engineer with deep practical knowledge of modern AI systems.

You should be comfortable building complex systems from first principles rather than assembling demos from existing frameworks.

Strong experience in several of the following areas is expected:

- **Software engineering:** exceptional Python skills; backend and systems architecture; APIs; asynchronous systems; distributed systems; testing; CI/CD; Git; production-quality engineering.
- **LLMs & Generative AI:** frontier and open-weight models; tool/function calling; structured generation; context engineering; model routing; inference optimization; quantization; fine-tuning where appropriate.
- **Agentic systems:** agent architectures; planning and execution loops; tool use; orchestration; delegation; human-in-the-loop systems.
- **AI coding systems:** state-of-the-art coding agents; repository-level reasoning; automated code generation and review; test generation; debugging; software-engineering benchmarks.
- **Memory & knowledge systems:** RAG; embeddings; vector search; knowledge graphs; context management and compression; retrieval; provenance.
- **Evaluation:** LLM and agent evaluations; automated testing; adversarial evaluation; independent reviewer/critic architectures; regression suites; observability and reliability measurement.
- **Data science:** strong numerical reasoning; Python scientific stack; statistics; data pipelines; experimentation; model evaluation and reproducibility.
- **Model infrastructure:** local inference; GPU deployment; model serving; batching and caching; containers; orchestration; heterogeneous compute.
- **Security:** secure-by-design architecture; authentication and authorization; secrets management; encryption; sandboxing; network isolation; auditability; supply-chain security.
- **Networking & on-prem infrastructure:** Linux; Docker/containers; private networking; VPN/tailnet architectures; service discovery; secure communication across multiple machines and compute nodes.
- **Databases & storage:** SQL; object storage; vector databases; caching; durable data architectures for AI systems.

You do not need to be an expert in every area above. We care more about exceptional engineering ability, intellectual range, speed of learning and the ability to reason across the full system.

### Particularly relevant experience

We would be especially interested in candidates who have worked deeply with autonomous coding agents, multi-agent systems, local LLM infrastructure, AI evaluation systems, secure AI infrastructure or advanced developer tooling.

Experience operating open-weight models on local GPU infrastructure is valuable.

Experience in security-sensitive, sovereign, air-gapped or on-premise environments is a strong plus.

Experience in defense is not required.

### The Technical Challenge

The frontier of generative AI is moving extraordinarily quickly. Models are becoming more capable, agents more autonomous, and the boundary between model capability and software infrastructure increasingly blurred.

The challenge is to turn these rapidly evolving capabilities into reliable, secure and production-grade systems. That means solving hard problems across model selection and routing, inference, tool use, orchestration, context management, evaluation, verification, observability, security and infrastructure — while maintaining the flexibility to incorporate new models and approaches as the state of the art evolves.

---

## La phrase qui structure tout le reste

> *building complex systems from first principles rather than assembling demos from existing frameworks*

L'opposition ne porte pas sur la philosophie, elle porte sur `demos` : ne pas assembler du framework qui démo bien et casse en production. Concrètement, sur un agent, ça veut dire posséder quatre choses que toute abstraction retire — **la boucle** (donc le prompt exact qui part), **le contexte** (ce qui entre dans la fenêtre, dans quel ordre, ce qui saute quand ça déborde), **les outils** (des fonctions à soi, dont l'erreur revient au modèle sous une forme choisie) et **l'évaluation**. Contrainte supplémentaire ici, jamais dite mais présente partout dans l'annonce : en air-gapped, la moitié de l'écosystème est inutilisable — télémétrie hébergée, appels cloud, résolution de paquets.

⚠️ **La question qui teste une équipe qui dit ça :** *qu'est-ce que vous avez construit vous-mêmes, et quel framework vous a lâchés pour que vous le fassiez ?* Sans réponse datée et précise, « first principles » veut dire syndrome du pas-inventé-ici.
