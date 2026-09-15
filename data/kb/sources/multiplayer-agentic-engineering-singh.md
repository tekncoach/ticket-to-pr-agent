# Multiplayer agentic engineering — Arjun Singh

| | |
|---|---|
| **Vidéo** | [Multiplayer agentic engineering](https://www.youtube.com/watch?v=OL7kfezynJM) |
| **Intervenant** | Arjun Singh, Superconductor |
| **Chaîne** | AI Engineer · publiée 2026-08-09 · 18 min 44 |
| **Contexte** | Une équipe qui travaille ensemble depuis dix ans, qui a intégré les agents de façon agressive et documenté les points de friction |

> *« A lot of people are talking about putting the agents at the center of
> everything. But you don't see a lot of people talking about the people. »*

---

## Ce qu'on en retire d'abord : la réponse au problème du slop

C'est la contribution la plus directement actionnable, et elle tient dans **deux
champs de formulaire**.

![Champs de critères](images/singh-09-acceptance-and-verification-criteria-form.png)

- **Acceptance criteria** — *« What must be true for the work to count as done? »*
- **Verification criteria** — *« What should agents run, inspect, or prove before they finish? »*

Les deux sont **déclarés à la création du ticket**, avant que l'agent ne commence.
La distinction est fine et elle porte tout : le premier décrit l'état visé, le
second décrit **la preuve** que l'agent doit produire.

### Pourquoi ça règle ce que nos gates ne règlent pas

Nos gates actuelles sont **génériques** : `artifacts_exist`, `files_non_empty`,
`diff_matches_claims`. Elles vérifient la même chose quelle que soit la demande,
donc elles ne peuvent constater que des propriétés universelles — un fichier
existe, il n'est pas vide. Aucune ne peut dire « ce code fait ce qui était
demandé », parce que ce qui était demandé n'est écrit nulle part sous une forme
vérifiable.

Le reviewer comble ce trou, mais tard et cher : sur notre run SDLC il a coûté
**54 % du budget** et n'a jamais approuvé. Des critères déclarés en amont
transformeraient une partie de son jugement en vérification mécanique — et,
détail qui compte, **c'est le même travail que le dialogue de clarification de
[US-30](../../user-stories/US-30-dialogue-de-clarification-avant-dispatch.md)**. L'orchestrateur ne pose pas des questions pour meubler : il
extrait ces deux champs.

L'anecdote est jolie et il la raconte à froid : quelqu'un de passage sur leur
stand a dit vouloir que les agents aient des critères clairs avant de se
déclarer finis. Personne n'a créé de ticket. Le bot de réunion a saisi l'idée,
ouvert le ticket, et **implémenté ces deux champs dans leur propre produit**.

---

## Les six leçons

### 0. Être agnostique au modèle et au harnais

*« The best model and harness can change weekly. »* Et l'argument qui pique :
**les intérêts de ceux qui vous vendent des tokens ne sont pas les vôtres.**
Vous acceptez de payer ce qu'il faut, pas davantage.

Nous y sommes déjà par construction : `agents.py` porte une table `BACKENDS`,
les ADW nomment des agents et **jamais des modèles**, et changer de modèle est
une ligne de YAML — on l'a fait pour le reviewer, divisant son coût par 3,3.

### 1. Transformer chaque interface humaine en interface agent + humain

Le point n'est pas d'avoir un bot Slack. C'est que **la même session d'agent**
soit joignable depuis Slack, l'application et GitHub. Un collègue qui relit une
PR pose sa question *dans le fil*, à l'agent, au lieu d'attendre le réveil de
l'auteur.

![Même session partout](images/singh-02-lesson1-same-session-from-every-interface.png)

Chez nous la primitive existe déjà : les sessions persistent sur disque et
`--adw-id` fait reprendre à chaque agent sa fenêtre de contexte. Ce qui manque,
c'est de l'**exposer** — c'est [US-43](../../user-stories/US-43-serveur-mcp-pour-piloter-la-plateforme.md) (MCP) et [US-17](../../user-stories/US-17-notifier-en-retour-dans-le-canal.md) (notifier dans le canal).

### 2. Rendre le travail de l'agent visible et collaboratif

Voir **qui** est intervenu sur une session compte autant que voir le résultat —
surtout quand le travail est déclenché par quelqu'un de non technique. *« Est-ce
qu'un ingénieur a validé ça ou pas ? »*

Et la forme qui rend ça lisible : **l'artefact**. L'agent produit une capture ou
une vidéo de ce qu'il a fait, visible depuis n'importe quelle interface.

### 3. Transformer chaque signal externe en code évaluable

Sources citées : Slack, réunions, bug trackers, appels commerciaux, rapports de
bug, demandes de fonctionnalité par e-mail.

![Sources de signaux](images/singh-06-lesson3-signal-sources.png)

**La réunion comme source d'événements** est ce qu'on n'avait pas dans [US-28](../../user-stories/US-28-bus-d-evenements-entrants.md).
Leur bot est resté quatre heures dans un Google Meet et en a tiré des tickets,
en **liant à du travail existant** quand il en trouvait — exactement la
déduplication de [US-31](../../user-stories/US-31-verifier-les-tickets-existants-avant-de-creer-du-tra.md).

Sa formulation du bénéfice mérite d'être retenue telle quelle : chaque appel
client produit des dizaines d'idées prototypées et **quelques PR réellement
livrables**, sans que personne ne transporte une demande d'un système à l'autre.

### 4. Des environnements de dev cloud, et la vraie raison

Il écarte l'argument attendu — fermer son ordinateur, la *lid anxiety* — pour
donner le bon : **le moindre privilège**.

> *« An agent told to wipe the staging database, resourceful and eager to
> comply, can find a token on a developer's machine that happens to point at
> production. »*

![Sandboxing réseau](images/singh-12-network-sandboxing-allow-deny.png)

Le **sandbox réseau configurable** est une idée qu'on n'a pas : liste
d'autorisation explicite, et une demande d'accès à un domaine inconnu déclenche
une confirmation plutôt qu'un blocage sec. Ça protège contre l'exfiltration,
pas seulement contre la casse.

Troisième bénéfice, décisif pour notre produit : **c'est ce qui permet à des
non-techniciens de déclencher du vrai travail.** Leur support et leur growth
livrent des correctifs sans environnement de développement. C'est exactement
notre agent client de [US-21](../../user-stories/US-21-plusieurs-agents-par-projet-avec-des-droits-differen.md).

### 5. Benchmarker les agents sur son propre codebase

![Benchmark](images/singh-14-benchmark-prs-agents-quality-vs-cost.png)

On sélectionne des PR qui représentent du bon travail dans **son** dépôt, on
choisit les agents à comparer, et on obtient qualité contre coût et contre temps.

L'argument est imparable : *« SWE-bench is all in Python, we're Ruby on Rails. »*
Un benchmark public mesure des tâches qui ne sont pas les vôtres. Pour une
agence qui vend du Rails, c'est encore plus vrai.

---

## Leurs chiffres, et ce qu'ils disent

![Tableau de bord](images/singh-15-usage-dashboard-by-agent-by-user.png)

| | |
|---|---|
| Tokens sur un mois | 10 594 M |
| Valeur en tokens | 19 622 $ — dont **16 699 $ couverts par des abonnements** |
| Dépense API réelle | 2 923 $ |
| PR fusionnées | 266 · +592 134 / −42 211 lignes |
| Claude Code | 3 382 runs · 1 163 $ de coût API · 10 132 $ de valeur |
| Codex | 12 821 runs · 1 417 $ · 9 147 $ de valeur |

**La distinction « valeur en tokens » contre « dépense API » est exactement ce
qui manque à [US-23](../../user-stories/US-23-couts-et-facturation-par-client.md).** Ce qu'un run *coûterait* au tarif public et ce qu'il
a *réellement* coûté sont deux nombres différents, et une agence qui refacture
doit tenir les deux : l'un justifie la valeur auprès du client, l'autre mesure
la marge.

Leur ventilation **par agent et par utilisateur** est la maquette de ce qu'il
nous faut par client et par projet.

> **Résultat : 99 % des PR sont générées par des agents. 100 % sont relues par
> un humain *et* par un agent.**

Le second chiffre compte plus que le premier. À ce volume, ils n'ont pas retiré
l'humain — ils ont ajouté un agent **à côté** de lui.

---

## Ce que ça complète dans notre backlog

| Apport | Où ça va |
|---|---|
| Critères d'acceptation et de vérification déclarés en amont | **nouvelle US** — c'est la réponse au slop |
| Revue de qualité déclenchée par la PR, imposée par la CI | **nouvelle US** |
| Benchmarker les agents sur le codebase du client | **nouvelle US** |
| Sandbox réseau avec liste d'autorisation | complète [US-22](../../user-stories/US-22-garde-fous-et-autorisation-avant-dispatch.md) |
| Réunions comme source d'événements | complète [US-28](../../user-stories/US-28-bus-d-evenements-entrants.md) |
| Valeur en tokens ≠ dépense réelle | complète [US-23](../../user-stories/US-23-couts-et-facturation-par-client.md) |
| Même session depuis toutes les interfaces | complète [US-43](../../user-stories/US-43-serveur-mcp-pour-piloter-la-plateforme.md) |
| Artefacts (captures) comme sortie visible | complète [US-33](../../user-stories/US-33-vue-des-pr-en-attente-de-validation.md) |
