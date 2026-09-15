# Agents, codebases, and teams — Aditya Khandelwal

| | |
|---|---|
| **Vidéo** | [Agents, codebases, and teams](https://www.youtube.com/watch?v=aeTb5BdmTTc) |
| **Intervenant** | Aditya Khandelwal, Amazon AGI Lab |
| **Chaîne** | AI Engineer ([@aiDotEngineer](https://www.youtube.com/@aiDotEngineer)) |
| **Publiée** | 2026-08-11 · 16 min 56 |
| **Contexte** | Retour d'expérience sur l'adoption des agents dans une équipe de dix personnes |

> *« Leave agent adoption to individuals and the engineer shipping two PRs a day
> ends up reviewing the ten that the early adopter ships. They fall further
> behind, the code they are reading is worse, and they conclude the agents are
> the problem. »*

---

## Ce qu'on en retire, mesuré chez nous

La contribution la plus directe de cette conférence à notre factory n'est pas un
principe : c'est **un seuil chiffré**. En Q&A, il donne le test de la disclosure
progressive — regarder combien de contexte un agent brûle sur son **premier
prompt**. Environ 20-25k tokens partent de toute façon ; au-delà de 40-50k,
« something's wrong ».

Test appliqué à nos propres runs, depuis la base de trace :

| Demande | Tokens | Coût |
|---|---|---|
| `list the top-level directories in this repo` | 15 320 | 0,011 $ |
| `reply with a one-line summary of this repo` | 47 044 | 0,022 $ |
| `reply with exactly: REGRESSION_OK` | 132 603 | 0,043 $ |
| `say ok in one word` | **495 325** | 0,082 $ |
| `reply with exactly: REGRESSION_OK` | **866 113** | 0,163 $ |
| `Build a minimal CRUD web interface` (SDLC complet) | 2 272 985 | 0,754 $ |

**Nos demandes triviales coûtent parfois plus cher que le vrai travail.**
866 000 tokens et 16 centimes pour faire dire un mot à un agent. C'est
exactement le symptôme qu'il décrit — *« it's silently burning context and money,
you don't realize it »* — et nous ne l'avions pas vu.

La cause est identifiable : le `user.md` du scout lui ordonne de chercher dans le
codebase et d'écrire ses trouvailles, **quelle que soit la demande**. Il n'a
aucune notion de « celle-ci ne nécessite aucune recherche ». Consigné en
[D-6](../../user-stories/dette-technique.md).

---

## Les symptômes d'un mauvais montage

Sa liste, et où nous en sommes :

| Symptôme | Chez nous |
|---|---|
| On materne les agents | Non — les ADW tournent détachés, y compris en sandbox |
| « le modèle est bête aujourd'hui » | Le modèle n'a pas changé, **le harnais si**. Nous l'avons vécu : `pi` déprécié avait supprimé `--session-id` |
| Brûler du contexte et de l'argent en silence | **Oui, mesuré ci-dessus** |
| Sessions interminables avec interventions constantes | Non — les phases sont bornées et les gates tranchent |
| Usine à slop | Partiellement contenu : le reviewer a refusé un run 8/8 vert |

---

## Les principes, et ce qu'ils valent pour nous

### Disclosure progressive — déjà en place, et validé de l'extérieur

Il insiste : un `SKILL.md` ne doit pas dépasser ~100 lignes, **un skill est un
dossier**, et le fichier d'entrée doit être un index fin qui pointe vers les
bons fichiers.

C'est exactement l'architecture de SSSF, qui l'énonce même comme règle : neuf
cookbooks chargés paresseusement, un par requête, et le `SKILL.md` interdit
explicitement de tout lire d'avance — *« reading it early defeats the
mechanism »*. Deux sources indépendantes qui convergent, c'est un signal.

### Smart prompt injection — la documentation vit dans le code

Son exemple : si un fichier a un runbook, **le runbook doit être dans le
commentaire**, pour qu'un agent qui `grep` jusqu'à ce fichier trouve d'où venir.
Le codebase devient une carte que l'agent parcourt au moment où il en a besoin.

Applicable directement à notre `adws/adw_modules/` — dont les commentaires font
déjà ça, en citant des échecs mesurés plutôt qu'en décrivant le code. Applicable
aussi aux dépôts clients : c'est une pratique à installer, pas seulement à
subir.

### Fermer la boucle — le slop est inévitable

Il ne dit pas « évitez le slop », il dit qu'il y en aura et qu'il faut **un
pipeline pour le détecter et s'auto-réparer**. Chez nous ce sont les gates — et
[D-1](../../user-stories/dette-technique.md) montre que la nôtre est faible : `diff_matches_claims` ne regarde jamais
le diff.

Idée neuve à retenir : **un « code gardener » qui tourne chaque nuit** et vérifie
l'organisation du code. Ce que « bien organisé » veut dire dépend du codebase —
donc, chez nous, du profil client ([US-42](../../user-stories/US-42-profil-de-configuration-par-client.md)).

### Une seule compétence à forte valeur : « ship it »

Leur pari a été d'investir dans **une** compétence : de « code fini » à « PR prête
à relire ». Elle ouvre la PR, écrit la description, traite les commentaires de
revue, **et répare les échecs de CI**. Elle tourne souvent plus d'une heure.

C'est [US-01](../../user-stories/US-01-ouvrir-une-pull-request-a-la-fin-d-un-run.md) et [US-02](../../user-stories/US-02-commits-atomiques-sur-la-partie-code.md) réunies, en plus ambitieux : notre chaîne s'arrête au
commit local. Le détail qui compte est **pourquoi** ça a marché socialement —
c'est la première chose qui a montré aux sceptiques que l'agent pouvait
travailler sans être materné.

### La durée est une bonne nouvelle, pas un défaut

*« It's good if agents take too long. That means you can actually go off and do
other things. »* Depuis le paradigme du raisonnement, plus l'agent réfléchit,
meilleure est la sortie.

À reprendre dans notre communication client ([US-17](../../user-stories/US-17-notifier-en-retour-dans-le-canal.md)) : ne pas s'excuser d'un
run qui dure. Un run de 2 minutes qui produit une PR relisible est un bon
échange, et le dire est un travail de cadrage d'attente.

---

## Le piège qui nous concerne comme produit

**La charge de revue.** Celui qui livre deux PR par jour se retrouve à relire les
dix de l'early adopter. Il prend du retard, le code qu'il lit est moins bon, et
il en conclut que les agents sont le problème.

Ce n'est pas une anecdote d'équipe interne : **c'est ce que notre produit va
faire subir à l'équipe de nos clients.** Une factory qui ouvre des PR dans le
dépôt d'un client déplace le travail vers ses développeurs. Si on ne traite pas
ça, on vend un générateur de charge de revue.

Conséquences concrètes pour le backlog :
- [US-02](../../user-stories/US-02-commits-atomiques-sur-la-partie-code.md) (commits atomiques) cesse d'être un confort : c'est ce qui rend une PR
  relisible en quelques minutes plutôt qu'en une heure.
- [US-03](../../user-stories/US-03-ecrire-des-tests-pas-seulement-les-reparer.md) (écrire les tests) réduit la charge de vérification manuelle.
- [US-33](../../user-stories/US-33-vue-des-pr-en-attente-de-validation.md) (vue des PR en attente) doit montrer **la file**, pas seulement les
  PR — une file qui s'allonge est le signal d'alerte.

### L'adoption est un problème d'équipe, pas d'individu

Son cadrage en deux axes — **peur** et **confiance dans l'usage** — vaut pour les
développeurs de nos clients. Ils ne sont pas neutres devant une PR écrite par un
agent d'agence. Et les changements qui marchent (restructurer un codebase pour
la disclosure progressive, converger sur un setup partagé) ne sont pas des
changements qu'un développeur seul peut faire.

Pour l'onboarding client ([US-06](../../user-stories/US-06-onboarding-in-app-d-un-nouveau-client.md)), ça veut dire que **l'accord du dirigeant ne
suffit pas** : l'équipe technique doit être embarquée, et pouvoir éditer le
setup partagé — c'est son critère à lui pour savoir qu'un sceptique a
réellement adhéré.

---

## Ce qu'ils ont cassé, et que nous éviterons

- **4 500 issues ouvertes en deux semaines.** Des agents créant des tickets les
  uns contre les autres, faute d'être câblés correctement. C'est précisément le
  scénario que [US-31](../../user-stories/US-31-verifier-les-tickets-existants-avant-de-creer-du-tra.md) (vérifier les tickets existants avant d'en créer) anticipe —
  et il montre que ça arrive vite.
- **Merge hell.** À prévoir dès que plusieurs runs travaillent sur un même
  codebase — lié à [US-08](../../user-stories/US-08-git-worktree-dans-la-vm.md) et [US-09](../../user-stories/US-09-l-orchestrateur-choisit-worktree-ou-nouvelle-sandbox.md).
- **Le retour au maternage.** Dès que le setup déçoit, les gens reviennent
  surveiller leur agent. Sa réponse : reprendre le retour et **l'injecter dans la
  compétence**, plutôt que laisser chacun contourner.

### Laisser les prototypes sortir du cadre

Un prototype n'a pas vocation à être livré. Il doit pouvoir **opter hors de tous
les standards rigoureux** du codebase. À traduire chez nous en un mode déclaré
dans le profil client ([US-42](../../user-stories/US-42-profil-de-configuration-par-client.md)) : un projet ou une branche marquée « prototype »
saute les gates coûteuses.

---

## La phrase à retenir

> *« Instead of saying the model is so dumb, ask: how can I make it smarter? »*

Et il barre le mot *my* dans « my setup » : ce n'est pas un réglage personnel,
c'est **le setup partagé** dans lequel il faut investir. Pour nous, ce setup
partagé porte un nom — c'est le profil client de [US-42](../../user-stories/US-42-profil-de-configuration-par-client.md), et les prompts par
stack de [US-04](../../user-stories/US-04-prompts-dynamiques-et-editables-par-stack-technique.md).
