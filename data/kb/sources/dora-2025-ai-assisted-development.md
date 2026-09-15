# DORA 2025 — l'IA est un amplificateur, et ce que ça implique

Source : *State of AI-assisted Software Development*, DORA / Google Cloud,
octobre 2025 (v. 2025.2), 143 pages. Le PDF complet est dans ce dossier :
[`2025_state_of_ai_assisted_software_development.pdf`](2025_state_of_ai_assisted_software_development.pdf).
Une version abrégée en français est également présente ;
**c'est la version complète en anglais qui fait foi ici**, les numéros de page
renvoient à elle.

**Ce qu'il faut savoir avant de citer un seul chiffre de ce rapport.**
4 867 répondants (p. 103), enquête du 13 juin au 21 juillet 2025 (p. 4),
complétée par 78 entretiens semi-directifs menés en continu de juillet 2024 à
juillet 2025 (p. 50 et p. 115). Les répondants ont été **répartis aléatoirement
entre quatre parcours de questions** — IA, ingénierie de plate-forme,
sociocognitif, capacités IA (p. 114) : aucun répondant n'a répondu à tout, et
les sous-échantillons par chapitre ne sont pas publiés.

Et surtout : **tout est déclaratif**. Le débit, l'instabilité, la qualité du
code, la taille des lots — tout vient d'un questionnaire, rien d'un dépôt Git.
DORA le dit lui-même, dans une note de bas de page qu'on ferait bien de lire
avant de citer le rapport en réunion (note 20, p. 48) : cette année les auteurs
parlent de **comparaisons, pas d'effets**, *« nous ne voulons pas donner de
fausses assurances sur notre compréhension de la structure causale
sous-jacente »*.

---

## 1. La thèse, en une phrase

> *« AI's primary role in software development is that of an amplifier. It
> magnifies the strengths of high-performing organizations and the
> dysfunctions of struggling ones. »* (p. 3)

Le corollaire est financier, et c'est celui qui parle à un CTO :

> *« The greatest returns on AI investment come not from the tools themselves,
> but from a strategic focus on the underlying organizational system. »* (p. 3)

Sans cette fondation, dit le rapport, l'IA crée **« des poches localisées de
productivité qui sont ensuite perdues dans le chaos en aval »** (p. 3). C'est
la phrase la plus utile du rapport pour vendre du conseil, et elle est en page 3.

---

## 2. Le modèle des capacités — sept leviers, et ce que chacun amplifie

15 capacités candidates ont été testées ; **sept** ont montré une interaction
substantielle avec l'usage de l'IA (p. 50). Ce ne sont pas des pratiques qui
améliorent les résultats en soi — ce sont des **modérateurs** : elles changent
le signe et l'amplitude de ce que l'IA produit.

| Capacité | Ce que sa présence amplifie | Page |
|---|---|---|
| **Position claire et communiquée sur l'IA** | efficacité individuelle, performance organisationnelle, et **la friction devient bénéfique** (elle baisse). Avec moins de certitude : le débit | p. 51–52 |
| **Écosystèmes de données sains** | performance organisationnelle | p. 54 |
| **Données internes accessibles à l'IA** | efficacité individuelle **et qualité du code** | p. 55–56 |
| **Pratiques rigoureuses de contrôle de version** | efficacité individuelle (fréquence de commit) ; performance d'équipe (usage du *rollback*) | p. 56–57 |
| **Travail par petits lots** | performance produit, et la friction devient bénéfique — **mais réduit le gain d'efficacité individuelle** | p. 58–59 |
| **Centrage sur l'utilisateur** | performance d'équipe — et **son absence rend l'effet de l'IA négatif** | p. 60–61 |
| **Plates-formes internes de qualité** | performance organisationnelle — **mais rend la friction nuisible** | p. 62 |

Trois remarques que le rapport ne met pas en avant et qui comptent :

**DORA ne classe pas ces sept capacités.** Aucune n'est désignée comme le plus
gros amplificateur. C'est important parce que
[`maturity-scales-ai-engineering.md`](maturity-scales-ai-engineering.md) §8
attribue à DORA l'affirmation que la plate-forme interne est *« the biggest
amplifier »* des sept — **cette formulation n'apparaît nulle part dans le
rapport complet**. Elle vient d'une page web dérivée. Le rapport dit seulement
que la plate-forme est *« la condition stratégique préalable »* (p. 72), et
c'est un autre énoncé.

**Deux des sept capacités ont un effet à double tranchant.** Le travail par
petits lots **diminue** le gain d'efficacité individuelle apporté par l'IA
(p. 58) — DORA en tire une déduction élégante : si réduire les lots réduit le
gain, c'est que **le gain venait principalement du volume de code généré**, pas
de la qualité du travail. Et une bonne plate-forme interne **augmente** la
friction ressentie chez les gros adopteurs d'IA (p. 62), ce que les auteurs
interprètent comme le prix des garde-fous : la plate-forme *« empêche l'usage
inapproprié »*.

**Le centrage sur l'utilisateur est la seule capacité dont l'absence est
mesurée comme dangereuse.** Pas neutre : négative.

> *« In the absence of a user-centric focus, AI adoption has a negative impact
> on team performance. »* (p. 60)

Reformulé pour un comité de direction : **une équipe qui ne sait pas pour qui
elle code va plus mal avec l'IA que sans.**

---

## 3. Il n'y a pas d'échelle de maturité — il y a sept profils, et ils ne sont pas ordonnés

C'est le point le plus contre-culturel du rapport, et il faut le dire tel quel :
**DORA ne propose aucune échelle de niveaux.** Il propose une analyse en grappes
sur sept dimensions (performance d'équipe, performance produit, débit,
instabilité, efficacité individuelle, travail valorisant, friction, épuisement)
qui produit **sept archétypes non ordonnés** (p. 15), assortis d'un
avertissement explicite : *« les noms et descriptions de ces grappes sont une
interprétation des données »* (p. 16).

| Grappe | Nom | Part | Le trait qui la définit |
|---|---|---|---|
| 1 | Difficultés fondamentales | **10 %** | tout est bas, épuisement et friction élevés (p. 16) |
| 2 | Le goulot d'étranglement de l'héritage | **11 %** | livre régulièrement, mais la valeur est mangée par les problèmes de qualité ; beaucoup de travail non planifié (p. 17) |
| 3 | Contraint par le processus | **17 %** | systèmes stables, mais épuisement et friction élevés — *« un tapis roulant »* (p. 17) |
| 4 | Fort impact, cadence faible | **7 %** | performance produit et efficacité individuelle fortes, **débit faible et instabilité élevée** (p. 17) |
| 5 | Stable et méthodique | **15 %** | qualité et valeur élevées, débit dans un percentile bas, faible épuisement (p. 18) |
| 6 | Performeurs pragmatiques | **20 %** | débit au-dessus de la moyenne, faible instabilité, bien-être seulement moyen (p. 18) |
| 7 | Haut niveau harmonieux | **20 %** | positif partout, sur base technique stable (p. 18) |

**Ce qui sépare les meilleurs des autres est une phrase, pas un tableau :**

> *« Le compromis vitesse contre stabilité est un mythe. Les meilleurs
> performeurs (grappes 6 et 7) excellent sur les deux dimensions
> simultanément. »* (p. 19)

Et les grappes 6 et 7 pèsent **près de 40 % de l'échantillon** (p. 19) — donc
ce n'est pas un idéal théorique, c'est une population observée. Le
contre-exemple est la grappe 4 : *« la vitesse sans la stabilité est une
proposition dangereuse et insoutenable »* (p. 19).

**Ce que ça implique pour le guide de maturité.** Le corpus du dossier est bâti
sur des échelles ordonnées — Shapiro 0–5, Yegge 1–8, ACMM. DORA, avec le plus
gros échantillon de l'année, dit que **la structure de la réalité n'est pas une
échelle mais un espace à deux axes** (débit × instabilité, figure 10, p. 19)
sur lequel les équipes se répartissent en amas. Le désaccord est déjà identifié
dans [`maturity-scales-ai-engineering.md`](maturity-scales-ai-engineering.md)
§7 (*« Is there one ladder, or is the ladder the wrong shape? »*) et le rapport
complet le confirme sans ambiguïté : **DORA ne vend pas d'escalier.**

Le compromis honnête pour un guide client : garder l'échelle comme dispositif
de communication (c'est ce que recommande déjà la fiche des échelles, §9.3),
mais **poser le diagnostic sur les deux axes de DORA**, parce que ce sont eux
qui se mesurent.

---

## 4. Débit contre stabilité — ce que le rapport mesure vraiment

**Ce qui a changé depuis 2024.** Le rapport 2024 chiffrait, pour chaque
augmentation de 25 % de l'adoption de l'IA, **−1,5 % de débit et +7,2 %
d'instabilité** (rappelé p. 35). Ce sont les seuls pourcentages de ce type que
DORA ait publiés, et ils datent de 2024.

**Ce que dit 2025.** Trois relations se sont inversées, une a tenu bon :

- le **travail valorisant** passe de négatif à positif (p. 42) ;
- le **débit de livraison** passe de négatif à positif (p. 42) ;
- la **performance produit** passe de neutre à positive (p. 42) ;
- l'**instabilité de livraison** reste positivement associée à l'IA — c'est-à-dire
  qu'elle **augmente** (p. 39, p. 43).

Sur la friction et l'épuisement : **aucune relation mesurable**, ni bonne ni
mauvaise (p. 39). Les auteurs les attribuent au système socio-technique, pas à
l'outil : *« l'IA a tendance à se présenter au clavier »* (p. 39) alors que
friction et épuisement *« résident au-delà du champ d'action de l'individu »*.

**Le résultat que personne ne cite et qui est le plus dur.** DORA a testé
l'argument « l'instabilité est un prix acceptable pour la vitesse ». Réponse :

> *« Nous n'avons trouvé aucune preuve d'un tel effet modérateur. Au contraire,
> l'instabilité continue d'avoir des effets délétères significatifs sur des
> résultats cruciaux comme la performance produit et l'épuisement, ce qui peut
> in fine annuler tout gain perçu en débit. »* (p. 41)

Autrement dit : **l'IA ne rend pas l'instabilité moins coûteuse.** Le débit
gagné et la stabilité perdue ne se compensent pas — ils s'additionnent avec des
signes opposés sur des résultats différents.

**L'ordre de grandeur, et pourquoi il faut être prudent.** La figure 1 (p. 4,
reprise en figure 28 p. 38) place tous les effets estimés dans une fourchette
étroite, **environ −0,05 à +0,20 en effet standardisé**, avec des intervalles
crédibles à 89 %. L'ordre décroissant des effets y est lisible : efficacité
individuelle, **instabilité de livraison**, performance organisationnelle,
travail valorisant, qualité du code, performance produit, débit, performance
d'équipe, épuisement, friction.

Deux choses à en retenir. D'abord, **le deuxième plus gros effet mesuré de
l'adoption de l'IA dans tout le rapport est une augmentation de l'instabilité**
— et c'est le seul du haut de liste qui soit indésirable. Ensuite, ces effets
sont **petits** : un écart-type d'adoption d'IA achète une fraction d'écart-type
de résultat. Le rapport est un rapport d'associations modestes, pas de
transformations spectaculaires.

*Limite assumée : les valeurs numériques exactes par résultat ne sont pas
imprimées dans le rapport — elles n'existent que comme positions sur une figure
vectorielle. Je n'ai extrait que l'ordre et la fourchette globale des axes.*

---

## 5. La confiance : le déclaré, le mesuré, et le piège de mesure

**Le déclaré est massivement positif.**

- **90 %** des répondants utilisent l'IA au travail, soit **+14,1 %** en un an
  (p. 24) ; **47 %** l'utilisent quotidiennement (p. 34) ; médiane de **2 heures**
  d'interaction sur la dernière journée travaillée, soit un quart d'une journée
  de huit heures (p. 25).
- **Plus de 80 %** perçoivent une hausse de leur productivité — mais dans le
  détail : 13 % « extrêmement », 31 % « modérément », **41 % « légèrement »**
  (p. 30).
- **59 %** perçoivent une amélioration de la qualité de leur code, dont 31 %
  seulement « légèrement » ; 30 % ne voient aucun impact (p. 30).

**Le réservé est plus gros qu'on ne le dit.**

- Confiance dans la qualité de la sortie IA : 4 % « énormément », 20 %
  « beaucoup », **46 % « plutôt »**, 23 % « un peu », 7 % « pas du tout »
  (p. 31). DORA résume : 70 % expriment un certain degré de confiance, **30 %
  ont peu ou pas confiance** (p. 4).
- L'usage **réflexe** — se tourner vers l'IA par défaut face à un problème — est
  minoritaire : **7 % « toujours »**, 27 % « la plupart du temps », 39 %
  « parfois » (p. 26).
- Le **mode agent** est marginal : **61 % ne l'utilisent jamais**, contre 38 %
  pour le mode collaboratif, 10 % pour le chat (p. 29). Les surfaces dominantes
  restent le chatbot (55 %) et l'IDE (41 %) ; les chaînes d'outils automatisées
  plafonnent à **18 %** (p. 29).

**Déclaré contre mesuré.** DORA cite METR directement, et sans ménagement :

> *« des développeurs ralentis de 19 % par les outils IA croyaient malgré tout
> que ces outils les avaient rendus 20 % plus efficaces. »* (p. 35)

Et le rapport en tire la conclusion qui l'engage : *« ces signaux contradictoires
nous indiquent qu'il faut davantage de travail fondé sur des preuves »* (p. 35).

**Le piège de mesure, et il est structurel.** DORA construit son facteur
« adoption de l'IA » à partir de **trois** items : la dépendance, l'**usage
réflexe**, et la **confiance** (p. 36, définition reprise p. 139). Les trois
sont fusionnés en un seul facteur latent parce qu'ils bougent ensemble.

Conséquence directe, et le rapport ne l'écrit pas : **la confiance est à
l'intérieur de la variable explicative**. Quand le rapport dit « les personnes
avec une adoption d'IA plus élevée déclarent une meilleure qualité de code »
(p. 38), il dit aussi, mécaniquement, « les personnes qui font plus confiance à
l'IA déclarent que le code de l'IA est meilleur ». Sur un jeu de données
entièrement auto-déclaré, cette boucle n'est pas séparable. Les auteurs
assument le choix — la boucle confiance → usage → confiance est *« un candidat
parfait pour un facteur »* (p. 36) — mais l'effet de bord est qu'**aucun
résultat perceptuel de ce rapport ne peut être lu comme une mesure
indépendante de la qualité de l'IA.**

Les résultats qui échappent à ce piège sont ceux qui portent sur des
comportements et des systèmes : les sept capacités, la taille des lots, la
distribution des grappes, l'instabilité.

---

## 6. Revue de code, taille des changements, goulot d'étranglement

C'est la partie que Pierre attend, et c'est celle où le rapport est le plus
frustrant : **DORA ne mesure pas la revue de code.** Pas de taille de PR, pas de
délai de revue, pas de nombre de relecteurs, pas de file d'attente. Rien.

Ce qu'il y a, et qui compte quand même :

**La taille des lots est mesurée — par questionnaire.** Trois indicateurs :
nombre approximatif de lignes commitées dans le dernier changement, nombre de
changements agrégés par déploiement, durée d'une tâche assignée (p. 58). C'est
la seule approche du sujet « taille du changement » dans tout le rapport.

**Le lien entre grosse taille et revue est une hypothèse, écrite comme telle.**

> *« Nous avons émis l'hypothèse que c'est probablement, en partie, parce qu'il
> est plus difficile de relire de plus gros lots de code. »* (p. 57)

Le verbe est *hypothesized*. DORA n'a pas testé cette relation ; il la propose
pour expliquer pourquoi l'instabilité monte. Le seul étai empirique adjacent
est indirect : la capacité *rollback* amplifie la performance d'équipe, et les
auteurs suspectent que c'est lié à *« l'importance de pouvoir défaire
rapidement des changements quand on travaille avec de plus gros lots de code »*
(p. 57).

**Le conseil sur le goulot est dans le chapitre VSM, et il est bon.**

> *« Une équipe peut découvrir, en cartographiant, que les revues de code sont
> un goulot d'étranglement significatif. Forte de cette information, elle peut
> décider d'appliquer l'IA à améliorer le processus de revue, plutôt que
> d'utiliser l'IA pour simplement générer plus de code, ce qui ne ferait
> qu'exacerber le goulot. »* (p. 76)

C'est, mot pour mot, l'argument de la fiche
[`sota-software-factories-patterns.md`](sota-software-factories-patterns.md)
§3.1 — mais présenté par DORA comme un **exemple pédagogique de cartographie de
flux de valeur**, pas comme un résultat mesuré.

**Le chapitre « miroir » va un cran plus loin** et décrit l'aval comme le
facteur limitant : *« quand les développeurs utilisent l'IA et écrivent du code
plus vite, le code doit toujours passer par les files de test et de revue »*, et
*« le rythme global de livraison a peu de chances de changer significativement
tant que les flux de travail environnants ne sont pas mis à jour »* (p. 81).
Les pistes proposées — revues de première passe générées par l'IA, résumés de
diff structurés pour mettre en évidence les risques (p. 82) — sont des
suggestions, sans données derrière.

**Enfin, un chiffre d'usage rarement cité** : parmi les gens dont le métier
inclut la revue de code, **56 % s'appuient sur l'IA pour la faire** (p. 27) —
soit l'un des taux les plus bas du tableau des tâches, loin derrière l'écriture
de code neuf (71 %). Les développeurs délèguent beaucoup plus volontiers
l'écriture que la relecture. **C'est cohérent avec un goulot qui se creuse.**

---

## 7. Confrontation avec `sota-software-factories-patterns.md`

### 7.1 §3.1 — le goulot de la revue : DORA n'est pas le témoin qu'on croit

La fiche des motifs présente le goulot de la revue comme *« la seule
affirmation de cette recherche à quadruple corroboration indépendante »*, et
compte la **lignée DORA** comme l'un des quatre témoins, avec la mention
*« throughput +2–18 %, stability negative »* — sourcée non pas sur DORA mais sur
une reprise Augment Code.

**Le rapport complet oblige à corriger cette ligne sur trois points.**

1. **Le signe du débit a changé.** DORA 2025 mesure le débit en hausse, pas en
   baisse (p. 42). La formule *« throughput +2–18 %, stability negative »*
   décrit un état intermédiaire qui ne correspond ni à 2024 (débit −1,5 %,
   instabilité +7,2 %, p. 35) ni à 2025 (débit positif, instabilité toujours en
   hausse, effets standardisés non chiffrés).
2. **DORA 2025 ne publie aucun pourcentage.** Les seuls pourcentages de la
   lignée sont ceux de 2024. Toute citation d'un « +X % de débit selon DORA »
   pour 2025 est une invention ou une reprise du chiffre de l'an dernier.
3. **DORA ne corrobore pas le goulot de la revue — il l'hypothèse** (p. 57). Le
   témoin qu'on croyait mesuré est en réalité un témoin de raisonnement. Ce
   n'est pas une réfutation : c'est une dégradation de la force de preuve, et
   elle laisse le trépied académique (arXiv 2603.27249v3), vendeur (Anthropic)
   et communautaire (HN) porter la charge à trois.

**Ce que DORA apporte réellement à ce dossier**, et qui est nouveau : la seule
intervention testée sur la taille des changements — le travail par petits lots —
**améliore la performance produit et réduit la friction, tout en réduisant le
gain d'efficacité individuelle** (p. 58–59). C'est-à-dire que la mesure qui
soulage le goulot est aussi celle qui **enlève au développeur la sensation
d'aller vite**. Voilà le vrai mécanisme du plateau de Shapiro au niveau 3,
mesuré pour la première fois : ce n'est pas que la revue devienne impossible,
c'est que **la solution est ressentie comme une régression par la personne à
qui on la demande.**

### 7.2 §3.5 — le coût : silence total, et c'est un résultat

La fiche des motifs pose *« 2–7 $ par tentative non triviale, 2–3 tentatives par
changement fusionné, donc 5–20 $ de dépense modèle par PR »*, et note que
personne ne publie le coût par PR fusionnée.

**DORA ne le publie pas non plus.** Il n'y a, dans 143 pages et 4 867
répondants, **aucune question sur la dépense** : pas de coût par tâche, pas de
budget de tokens, pas de prix des licences, pas de ROI chiffré. Le mot « coût »
n'apparaît que dans des emplois qualitatifs — coûts de coordination et de
vérification (p. 40), coûts d'API pour l'étiquetage dans un encadré
universitaire (p. 88), « précision, utilité et coût » comme axes à surveiller
(p. 83). Le seul montant de tout le rapport est macro-économique et emprunté :
**252,3 milliards de dollars** d'investissement mondial des entreprises dans
l'IA en 2024, cité du Stanford HAI AI Index (p. 34).

Le rapport frôle pourtant le sujet à deux reprises, sans jamais le chiffrer :
*« maximiser les bénéfices de l'IA peut exiger un investissement plus profond
que le simple achat de licences »* (p. 55, repris p. 64). C'est exactement la
bonne intuition — et elle reste sans dénominateur.

C'est un vide remarquable pour un rapport dont la thèse centrale est *« le
meilleur retour sur investissement IA »* (p. 3). **La plus grosse enquête de
l'année sur le développement assisté par IA ne demande à personne combien ça
coûte.** La fiche des motifs a donc raison sur le fond — le dénominateur est
faux partout — et DORA ne fournit ni confirmation ni réfutation de la
fourchette 5–20 $.

À utiliser tel quel en rendez-vous : quand un prospect dit « DORA dit que
l'IA marche », la question qui suit est « et DORA dit combien ça coûte ? ». La
réponse est : il ne le dit pas, il ne l'a pas demandé.

---

## 8. Confrontation avec `maturity-scales-ai-engineering.md`

**Là où DORA confirme la fiche.** Le §7 de la fiche identifie DORA comme la voix
qui refuse l'échelle unique — c'est exact et le rapport complet le durcit
(§3 ci-dessus). Le §8 liste les sept capacités correctement.

**Là où DORA contredit la fiche.**

**La citation « biggest amplifier ».** La fiche écrit : *« DORA names it
[a quality internal platform] the biggest amplifier of the seven capabilities »*
et l'appuie sur un extrait — *« an internal platform transforms individual AI
productivity into organizational impact »*. **Ni cette phrase ni ce classement
ne figurent dans le rapport complet.** Le rapport n'ordonne jamais les sept
capacités. La phrase la plus proche est *« votre plate-forme est la condition
stratégique préalable pour débloquer la valeur organisationnelle de l'IA »*
(p. 72) — une condition nécessaire, pas un maximum. La différence compte : « le
plus gros levier » est un conseil de priorisation, « condition préalable » est
un conseil de séquencement. **À corriger dans la fiche des échelles.**

**Le diagnostic du blocage.** La fiche §7 attribue à DORA la position *« les
équipes bloquent là où le système organisationnel est faible, en particulier la
plate-forme interne »*. Le rapport complet est à la fois plus large et plus
précis : la plate-forme est l'un des sept, et la seule capacité dont l'absence
soit mesurée comme **activement nuisible** est le **centrage sur l'utilisateur**
(p. 60, réaffirmé p. 95). Si l'on doit extraire un « diagnostic DORA » du
blocage, c'est celui-là.

**Là où DORA remplit un des cinq trous identifiés par la fiche.** Le §9.2 de la
fiche réclame *« une condition d'entrée sur le codebase, pas seulement sur
l'équipe »*. DORA fournit exactement le matériau : les 12 caractéristiques d'une
plate-forme interne de qualité (p. 140), les distributions de référence des cinq
métriques de livraison (p. 20–21) et la mesure de la taille des lots (p. 58)
forment ensemble une **grille d'audit d'entrée directement utilisable en
avant-vente** — et elle est publique, sourcée, et signée Google.

Quelques repères de cette grille, utiles pour situer un prospect Rails de
10–14 ans (p. 20–21) :

- **délai de mise en production** : 15 % < 1 jour, 9,4 % < 1 heure ; **43,5 %**
  sont au-delà de la semaine ;
- **fréquence de déploiement** : 16,2 % à la demande ; **24 %** déploient moins
  d'une fois par mois ;
- **taux d'échec des changements** : **37,9 % des répondants déclarent plus de
  16 %** d'échec ;
- **taux de reprise** (déploiements non planifiés pour corriger un bug
  utilisateur) : **47,4 % au-dessus de 16 %**.

Ces deux dernières lignes sont le meilleur outil de conversation commerciale du
rapport : la moitié du marché retravaille plus d'un déploiement sur six, **avant
même d'ajouter des agents.**

---

## 9. Ce que le rapport ne mesure pas — à dire avant qu'un prospect ne le découvre

- **Aucun coût, aucun budget, aucun ROI chiffré** (§7.2).
- **Aucune donnée de dépôt.** Pas un commit, pas une PR, pas un délai de revue
  observé. Tout est déclaratif ; le chapitre « frameworks de mesure » consacre
  d'ailleurs deux pages à expliquer que les métriques issues de logs **ne sont
  pas objectives non plus** (p. 91).
- **Aucune mesure de la revue de code** en tant que processus (§6).
- **Aucun résultat spécifique aux agents autonomes.** Avec 61 % de « jamais » en
  mode agent (p. 29), le rapport décrit un monde d'assistants, pas de factories.
  Le mot *agentic* apparaît comme perspective (p. 83), jamais comme mesure.
- **Aucune segmentation par âge de codebase, langage ou taille d'équipe** dans
  les résultats publiés — alors que le rapport dit lui-même bloquer les chemins
  de biais sur le langage et le rôle (p. 113).
- **Pas d'effets, des comparaisons** (note 20, p. 48). À répéter.

---

## Ce que cette lecture change pour nous

**Un.** Le rapport donne enfin une réponse défendable à la question « pourquoi
mon équipe va plus vite et mon produit ne va pas mieux ? » : parce que le gain
est individuel, que l'instabilité est systémique, et que **rien dans les données
ne montre que l'un compense l'autre** (p. 41). C'est l'argument d'ouverture du
guide.

**Deux.** Les sept capacités sont une liste de contrôle vendable, mais leur
valeur réelle est ailleurs : ce sont les **seules variables du dossier dont on
sache qu'elles changent le signe** de l'effet de l'IA. Deux d'entre elles —
données internes accessibles à l'IA (p. 55) et plate-forme interne (p. 62) —
décrivent littéralement ce que construit notre factory. C'est une caution
externe, datée et signée, pour un travail qu'on faisait déjà.

**Trois, et c'est l'inconfortable.** DORA mesure que réduire la taille des lots
**réduit le sentiment d'efficacité** (p. 58). Notre produit demandera exactement
ça à des équipes clientes. Il faut donc que la contrepartie soit visible ailleurs
— performance produit, friction en baisse — **et mesurée**, sinon la mesure sera
vécue comme une punition et abandonnée. C'est le même mur que le plateau du
niveau 3 chez Shapiro, vu depuis les données.
