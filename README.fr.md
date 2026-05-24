# NetAlps Infrahub Demo — CI/CD Réseau avec une Source Unique de Vérité

> 🌐 **Language / Langue :** [English](README.md) · [Français](README.fr.md)

> **Un lab pratique pour les ingénieurs réseau qui apprennent le NetDevOps.**  
> Construisez un réseau entièrement automatisé : définissez vos données une seule fois dans Infrahub, générez les configs, déployez des routeurs virtuels, validez avec pyATS, et prouvez que toute dérive du SSOT casse le réseau.

---

## Table des matières

1. [Ce que vous allez apprendre](#1-ce-que-vous-allez-apprendre)
2. [Concepts fondamentaux](#2-concepts-fondamentaux)
3. [Topologie réseau](#3-topologie-réseau)
4. [Architecture du SSOT](#4-architecture-du-ssot)
5. [Architecture du pipeline CI/CD](#5-architecture-du-pipeline-cicd)
6. [Prérequis](#6-prérequis)
7. [Guide pas à pas](#7-guide-pas-à-pas)
8. [Comprendre les tests](#8-comprendre-les-tests)
9. [Le démo de panne SSOT](#9-le-démo-de-panne-ssot)
10. [Comprendre le pipeline CI/CD](#10-comprendre-le-pipeline-cicd)
11. [Référence des fichiers du projet](#11-référence-des-fichiers-du-projet)
12. [Interface web Infrahub](#12-interface-web-infrahub)
13. [Dépannage](#13-dépannage)
14. [Pour aller plus loin](#14-pour-aller-plus-loin)

---

## 1. Ce que vous allez apprendre

Ce projet est une démonstration complète de bout en bout du **Network as Code** et du **CI/CD pour l'infrastructure réseau**. En le parcourant, vous comprendrez :

| Compétence | Ce que le projet démontre |
|---|---|
| **Conception d'un SSOT** | Comment modéliser un réseau dans Infrahub (schéma + données) de façon à ce que toute configuration en découle |
| **Génération de configs** | Comment interroger une API GraphQL et produire des configurations de routeurs de façon programmatique |
| **Création d'un lab virtuel** | Comment Containerlab démarre une topologie FRR à 4 routeurs avec une seule commande |
| **Validation de l'état réseau** | Comment pyATS teste les voisinages OSPF, les tables de routage, le BFD et le ping de bout en bout |
| **Audit de cohérence SSOT** | Comment comparer ce qui est *déployé* à ce qui est *attendu* dans le SSOT — et faire échouer le pipeline s'ils divergent |
| **Injection de panne** | Comment la mutation du SSOT (changer une seule valeur) se propage automatiquement au routeur et brise le réseau — prouvant que le SSOT est la vraie source de configuration |
| **CI/CD pour le réseau** | Comment un pipeline GitLab enchaîne tout cela : démarrage Infrahub → chargement des données → génération des configs → déploiement → tests → nettoyage |

### Ce que ce projet ajoute à `netalps_demo`

`netalps_demo` introduisait Containerlab + FRR + pyATS avec 2 routeurs et des configs statiques.  
Ce projet va plus loin sur trois axes :

| Axe | `netalps_demo` | Ce projet |
|---|---|---|
| Échelle | 2 routeurs | 4 routeurs en chaîne |
| Configuration | Fichiers statiques | Générée depuis le SSOT Infrahub |
| Validation | OSPF + ping | OSPF + table de routage + BFD + ping + **audit SSOT** |

---

## 2. Concepts fondamentaux

### 2.1 Source Unique de Vérité (SSOT)

Dans le réseau traditionnel, la même information est dupliquée à de nombreux endroits : la config de l'équipement, le tableur IPAM, le wiki de documentation, le système de supervision. Quand l'un d'eux diverge des autres, des incidents surviennent.

Une **Source Unique de Vérité** est un système où les paramètres réseau (adresses IP, zones OSPF, timers BFD, rôles des équipements…) sont stockés **une seule fois**, et tout le reste est **dérivé** de cet enregistrement unique :

```
SSOT (Infrahub)
    │
    ├──► generate_configs.py  →  frr.conf  →  poussé vers le routeur
    ├──► post_check.py         →  audit : le routeur correspond-il au SSOT ?
    └──► documentation, IPAM, supervision… (intégrations futures)
```

> **Idée clé :** Si la config du routeur ne correspond pas au SSOT, le pipeline échoue. Cela rend la dérive de config visible et bloquante.

### 2.2 Infrahub

[Infrahub](https://github.com/opsmill/infrahub) est une **source de vérité réseau** open-source développée par OpsMill. Il est :

- **Orienté schéma** — vous définissez votre propre modèle de données (ce qu'est un « routeur » ou une « interface »), et Infrahub le fait respecter
- **Natif GraphQL** — toutes les données sont interrogées et modifiées via une API GraphQL
- **Versionné comme Git** — Infrahub conserve l'historique complet de toutes les modifications (branches, diffs)
- **Conçu pour les réseaux** — avec des types intégrés pour les adresses IP, les préfixes, les ASN, etc.

Dans ce projet, Infrahub stocke l'intégralité du modèle de données réseau : équipements, interfaces, adresses IP, paramètres OSPF et timers BFD. Tout ce dont les routeurs FRR ont besoin se trouve dans Infrahub.

### 2.3 Containerlab

[Containerlab](https://containerlab.dev/) démarre des topologies réseau à partir de conteneurs Docker. Un seul fichier YAML décrit la topologie, et `containerlab deploy` démarre tous les nœuds, câble les liens virtuels et attribue les IPs de management — en quelques secondes.

Avantages pour un environnement d'apprentissage :
- Pas de matériel physique nécessaire
- Reproductible : chaque déploiement est identique
- Détruit proprement avec `containerlab destroy --cleanup`
- Supporte FRR, Nokia SR Linux, Arista cEOS, Cisco XRd, et bien d'autres

### 2.4 FRR (Free Range Routing)

[FRR](https://frrouting.org/) est une suite logicielle de routage Linux qui implémente OSPF, BGP, ISIS, BFD, et plus encore. Il tourne dans des conteneurs Docker et se configure via un fichier `frr.conf` qui est **généré depuis Infrahub** dans ce projet.

### 2.5 pyATS

[pyATS](https://developer.cisco.com/pyats/) (Python Automated Testing System) est le framework de test réseau de Cisco. Il fournit :
- Un modèle **testbed** pour décrire vos équipements (utilisé ici via `docker exec`)
- **aetest** — un framework de test structuré avec setup/teardown, sections de test, et suivi pass/fail
- Des rapports de test clairs et des codes de retour adaptés au CI/CD

Dans ce projet, les tests pyATS valident l'état du réseau après chaque déploiement.

### 2.6 OSPF et BFD (rappel rapide)

**OSPF** (Open Shortest Path First) est un protocole de routage à état de liens. Les routeurs échangent des LSA (Link State Advertisements) pour construire une carte complète du réseau, puis calculent l'arbre du plus court chemin. États clés : `Init → ExStart → Exchange → Loading → Full`. Seul **Full** signifie que la relation de voisinage est entièrement établie et que les routes sont échangées.

**BFD** (Bidirectional Forwarding Detection) est un protocole de détection rapide des pannes de lien, en millisecondes (bien plus rapide que les timers dead d'OSPF). Il s'exécute entre des paires de routeurs sur chaque lien point à point.

---

## 3. Topologie réseau

### Schéma physique

```
  host-left                                                         host-right
192.168.10.10/24                                                 192.168.40.10/24
     eth1                                                              eth1
      │                                                                 │
  eth2│ (LAN)                                                   (LAN) eth2│
┌──────────┐                    ┌──────────┐    ┌──────────┐                    ┌──────────┐
│frr-rtr-01│eth1──10.0.12.0/30──│frr-rtr-02│    │frr-rtr-03│──10.0.34.0/30──eth1│frr-rtr-04│
│ 10.0.0.1 │                    │ 10.0.0.2 │    │ 10.0.0.3 │                    │ 10.0.0.4 │
└──────────┘                    └──────────┘    └──────────┘                    └──────────┘
                                      eth2──10.0.23.0/30──eth1
```

Le trafic de bout en bout de `host-left` à `host-right` traverse les 4 routeurs.

### Tableau des équipements

| Équipement | Loopback | LAN (eth2) | Rôle | Voisins OSPF |
|---|---|---|---|---|
| frr-rtr-01 | 10.0.0.1/32 | 192.168.10.0/24 | Edge (gauche) | rtr-02 |
| frr-rtr-02 | 10.0.0.2/32 | — | Transit | rtr-01, rtr-03 |
| frr-rtr-03 | 10.0.0.3/32 | — | Transit | rtr-02, rtr-04 |
| frr-rtr-04 | 10.0.0.4/32 | 192.168.40.0/24 | Edge (droite) | rtr-03 |
| host-left  | — | 192.168.10.10/24 | Hôte de test | — |
| host-right | — | 192.168.40.10/24 | Hôte de test | — |

### Pourquoi cette topologie ?

Une chaîne de 4 routeurs est la topologie la plus simple qui possède à la fois des routeurs **edge** (un seul voisin) et des routeurs **transit** (deux voisins). Cela permet de tester :
- La propagation des routes sur plusieurs sauts
- La distinction entre interfaces OSPF passives et actives
- BFD sur plusieurs liens point à point indépendants
- L'impact d'une panne quand un routeur transit est mal configuré (une incompatibilité de zone sur rtr-03 isole les deux moitiés du réseau)

### Protocoles

- **OSPF Zone 0** sur tous les liens point à point et les loopbacks
- **BFD** sur tous les liens P2P (détection rapide des pannes, timers sub-seconde)
- **OSPF passif** sur les interfaces LAN (annoncé mais sans formation de voisinage avec les hôtes)

---

## 4. Architecture du SSOT

### Schéma

Infrahub utilise un **schéma personnalisé** (`infrahub/schema/network.yml`) qui définit deux types de nœuds dans l'espace de noms `Netalps` :

#### `NetalpsNetworkDevice`

Représente un routeur ou un hôte. Attributs principaux :

| Attribut | Type | Description |
|---|---|---|
| `hostname` | Text | Identifiant unique de l'équipement |
| `role` | Dropdown | `router` ou `host` |
| `loopback_ip` | IPHost | Adresse loopback (ex. `10.0.0.1/32`) |
| `ospf_router_id` | Text | Router-ID OSPF |
| `mgmt_ip` | IPHost | IP de management Containerlab |
| `clab_container` | Text | Nom du conteneur Docker pour `docker exec` |

#### `NetalpsInterface`

Représente une interface physique ou logique, liée à un équipement. Attributs principaux :

| Attribut | Type | Description |
|---|---|---|
| `name` | Text | Nom de l'interface (ex. `eth1`) |
| `ip_address` | IPHost | IP de l'interface |
| `peer_ip` | IPHost | IP du pair (pour la config BFD) |
| `ospf_enabled` | Boolean | OSPF actif sur cette interface |
| `ospf_passive` | Boolean | Mode passif (annoncé mais sans hello) |
| `ospf_area` | Text | Zone OSPF (ex. `0`) |
| `ospf_network_type` | Text | `point-to-point` pour les liens P2P |
| `bfd_enabled` | Boolean | BFD activé |
| `bfd_detect_multiplier` | Integer | Multiplicateur de détection BFD |
| `bfd_min_rx` / `bfd_min_tx` | Integer | Timers BFD en millisecondes |

### Flux de données : du SSOT à la config en production

```
┌─────────────────────────────────────────────────────────────────┐
│                    Infrahub (SSOT)                              │
│  Schéma : NetalpsNetworkDevice + NetalpsInterface               │
│  API : http://localhost:8000  (GraphQL)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                       │
    load_data.py     generate_configs.py        post_check.py
    (PUSH données)   (PULL → rendu frr.conf)   (PULL → audit)
           │                 │                       │
    1 seule fois       À chaque job CI          À chaque job CI
    (idempotent)             │                       │
                       configs/                 Compare config
                       frr-rtr-0X/             déployée vs SSOT
                       frr.conf
                             │
                       containerlab deploy
                             │
                     4 conteneurs FRR
                     (frr.conf monté en bind)
```

### Exemple de requête GraphQL

`generate_configs.py` interroge Infrahub avec une seule requête GraphQL pour récupérer tous les équipements et leurs interfaces en une fois :

```graphql
query GetNetworkDevices {
  NetalpsNetworkDevice {
    edges {
      node {
        hostname       { value }
        ospf_router_id { value }
        loopback_ip    { value }
        interfaces {
          edges {
            node {
              name              { value }
              ip_address        { value }
              ospf_enabled      { value }
              ospf_area         { value }
              bfd_enabled       { value }
              bfd_min_tx        { value }
              bfd_min_rx        { value }
            }
          }
        }
      }
    }
  }
}
```

La réponse est ensuite utilisée pour générer un `frr.conf` par équipement. Pas de templates Jinja2 — la config est construite en Python pur, ce qui rend la logique facile à lire et à étendre.

---

## 5. Architecture du pipeline CI/CD

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   infrahub   │───►│  configure   │───►│    deploy    │───►│  pre_check   │
│              │    │              │    │              │    │              │
│infrahub_start│    │generate_cfg  │    │deploy_lab    │    │pre_check.py  │
│load_schema   │    │              │    │              │    │              │
│load_data     │    │              │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────┬───────┘
                                                                    │
                    ┌──────────────────────────────────────────────►│
                    │                                               │
             ┌──────┴──────┐    ┌───────────────────────────────────┘
             │   cleanup   │◄───│           post_check              │
             │             │    │                                   │
             │cleanup_lab  │    │  post_check.py                    │
             │(toujours)   │    │  (OSPF + routes + BFD + ping +   │
             └─────────────┘    │   audit SSOT)                     │
                                └──────────────────────────────────┘
```

Le stage `cleanup` s'exécute **toujours** (même en cas d'échec) pour détruire le lab et arrêter Infrahub, garantissant que le runner ne reste jamais dans un état sale.

### Quand le pipeline se déclenche-t-il ?

Défini dans les règles workflow de `.gitlab-ci.yml` :
- Sur les événements de **merge request**
- Sur push vers **`main`**
- Sur push vers des branches correspondant à **`feature/*`** ou **`infrahub/*`**

---

## 6. Prérequis

### Connaissances

Ce projet convient si vous êtes à l'aise avec :
- La ligne de commande Linux de base (shell, Docker, variables d'environnement)
- Les fondamentaux du réseau IP (routage, sous-réseaux)
- Les bases d'OSPF (ce qu'est une relation de voisinage, ce que contient une table de routage)
- Les bases de Python (pour lire et modifier les scripts de test)

Aucune expérience préalable de pyATS, Infrahub ou Containerlab n'est requise — le projet est auto-explicatif.

### Outils

| Outil | Version | Installation |
|---|---|---|
| Docker | ≥ 24 | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Containerlab | ≥ 0.55 | [containerlab.dev/install](https://containerlab.dev/install/) |
| Python | ≥ 3.10 | système ou pyenv |

### Dépendances Python

À installer dans un environnement virtuel :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyats infrahub-sdk httpx pyyaml
```

### Images Docker

```bash
docker pull frrouting/frr:latest       # Routeur FRR
docker pull nicolaka/netshoot:latest   # Hôtes de test
```

---

## 7. Guide pas à pas

### Étape 0 — Démarrer Infrahub (le SSOT)

Infrahub tourne en tant que stack Docker Compose (Neo4j + RabbitMQ + Redis + le serveur Infrahub lui-même).

```bash
# Copier le fichier env exemple (adapter les mots de passe si nécessaire en production)
cp infrahub/.env.example infrahub/.env

cd infrahub
docker compose up -d
```

Puis attendre qu'il soit entièrement prêt (~2 minutes au premier démarrage) :

```bash
bash scripts/wait_for_infrahub.sh http://localhost:8000
```

> **Pourquoi attendre ?** Infrahub dépend de Neo4j et RabbitMQ avant d'accepter des appels API. Le script d'attente interroge `/api/health` jusqu'à obtenir un `200 OK`.

### Étape 1 — Charger le schéma (définir votre modèle de données)

Avant de pousser des données, Infrahub doit connaître les types d'objets qui existent. Le fichier de schéma définit les types de nœuds `NetalpsNetworkDevice` et `NetalpsInterface`.

```bash
source .venv/bin/activate

INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_API_TOKEN=satoken \
    infrahubctl schema load infrahub/schema/network.yml --branch main
```

> **Pourquoi un schéma personnalisé ?** Infrahub est générique — il ne sait pas ce qu'est un « routeur » tant que vous ne le lui dites pas. En définissant le schéma, vous rendez le modèle de données explicite : chaque champ a un type, une règle de validation et un libellé lisible. Vous pouvez ensuite l'étendre (ajouter un ASN BGP, un fournisseur, un numéro de série…) sans modifier les scripts du pipeline.

Vous pouvez vérifier que le schéma a été chargé dans l'interface web sur `http://localhost:8000` sous **Schema**.

### Étape 2 — Charger les données réseau (alimenter le SSOT)

```bash
INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_TOKEN=satoken \
    python infrahub/load_data.py
```

Ce script crée les 4 routeurs, les 2 hôtes et toutes leurs interfaces avec :
- Les adresses IP
- Les paramètres OSPF (zone, mode passif, type de réseau)
- Les timers BFD

Le script est **idempotent** — l'exécuter une deuxième fois met à jour les objets existants plutôt que de créer des doublons.

> **Pourquoi charger les données par programme ?** Dans un environnement réel, ces données viendraient d'un IPAM ou d'un CMDB existant via un script d'import. Ici elles sont codées en dur pour la clarté, mais le schéma est le même : les données circulent **vers** le SSOT depuis une source faisant autorité, et non l'inverse.

### Étape 3 — Générer les configs FRR depuis Infrahub (SSOT → Config équipement)

```bash
INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_TOKEN=satoken \
    python scripts/generate_configs.py
```

Cette commande interroge l'API GraphQL d'Infrahub et écrit un `frr.conf` pour chacun des 4 routeurs dans `configs/frr-rtr-0X/`.

Pour prévisualiser sans écrire de fichiers :

```bash
python scripts/generate_configs.py --dry-run
```

Pour régénérer un seul routeur :

```bash
python scripts/generate_configs.py --device frr-rtr-03
```

> **Pourquoi générer les configs ?** L'alternative serait de maintenir manuellement 4 fichiers `frr.conf` séparés et de les garder synchronisés entre eux et avec la documentation. La génération de config supprime les erreurs humaines : si la zone OSPF dans Infrahub est `0`, la config générée aura `ip ospf area 0`. Il n'est pas possible que la config dise zone `1` alors que le SSOT dit `0` — sauf si quelqu'un modifie le fichier manuellement (ce que le pipeline détecterait).

Après la génération, vous pouvez inspecter ce qui a changé :

```bash
git diff configs/
```

### Étape 4 — Déployer le lab

```bash
containerlab deploy -t topology.clab.yml
```

Containerlab lit `topology.clab.yml`, crée des conteneurs Docker pour chaque nœud, établit les liens virtuels entre eux et attribue les IPs de management. Les fichiers `frr.conf` de `configs/` sont montés en bind dans chaque conteneur FRR au démarrage.

> **Pourquoi Containerlab ?** Vous obtenez une topologie multi-routeurs réaliste sans matériel physique. Chaque conteneur FRR exécute une vraie pile de routage — les adjacences OSPF, le calcul SPF et les sessions BFD sont identiques à ceux d'un routeur physique.

### Étape 5 — Attendre la convergence OSPF

La convergence OSPF prend quelques secondes après le démarrage des conteneurs. pyATS gère cette attente automatiquement (voir [Comprendre les tests](#8-comprendre-les-tests)), mais si vous exécutez manuellement, attendez ~30 secondes avant d'inspecter la table de routage.

### Étape 6 — Lancer les tests pyATS

```bash
# Vérification de bon sens (conteneurs en marche, démons actifs, Infrahub accessible)
python tests/pre_check.py --testbed tests/testbed.yml

# Validation complète (OSPF + routage + BFD + ping + audit SSOT)
python tests/post_check.py --testbed tests/testbed.yml
```

Ou lancer les deux en un seul job pyATS :

```bash
pyats run job tests/test_job.py --testbed-file tests/testbed.yml
```

### Étape 7 — Nettoyage

```bash
containerlab destroy -t topology.clab.yml --cleanup
cd infrahub && docker compose down -v
```

L'option `--cleanup` supprime le répertoire `clab-frr-infrahub-demo/` créé par Containerlab.  
L'option `-v` supprime les volumes Docker (données Neo4j) pour que la prochaine exécution reparte de zéro.

---

## 8. Comprendre les tests

### `pre_check.py` — Vérification de bon sens

S'exécute **avant** toute validation réseau. Il vérifie :

| Test | Ce qu'il vérifie | Pourquoi c'est important |
|---|---|---|
| Conteneurs en marche | Les 6 conteneurs sont `Up` dans `docker ps` | Échouer rapidement si le lab n'a pas démarré correctement |
| Démons FRR | Les processus `ospfd` et `bfdd` sont actifs dans chaque routeur | Un conteneur peut tourner sans ses démons de routage |
| Infrahub accessible | HTTP `GET /api/health` retourne 200 | Nécessaire à `post_check.py` pour l'audit SSOT |

### `post_check.py` — Validation fonctionnelle complète

S'exécute **après** le déploiement. Il comporte 7 cas de test :

#### TestOSPF — Voisins OSPF

```
frr-rtr-01: vtysh -c "show ip ospf neighbor"  →  doit contenir "Full"
```

Vérifie que **chaque routeur** a au moins un voisin OSPF en état `Full`.  
Valide également le **nombre de voisins** : les routeurs edge doivent en avoir 1, les routeurs transit doivent en avoir 2.

> Si rtr-03 a une incompatibilité de zone OSPF (zone 1 au lieu de 0), ses voisinages avec rtr-02 et rtr-04 resteront bloqués en `ExStart/Exchange` et n'atteindront jamais `Full`. Ce test le détecte.

#### TestRouting — Table de routage

```
frr-rtr-01: vtysh -c "show ip route 192.168.40.0/24"  →  doit contenir "ospf"
```

Vérifie que les routeurs edge ont des routes OSPF vers :
- Le LAN distant (ex. rtr-01 apprend `192.168.40.0/24`)
- Tous les loopbacks distants (ex. rtr-01 apprend `10.0.0.2/32`, `10.0.0.3/32`, `10.0.0.4/32`)

> Ce test vérifie la propagation des routes sur les 4 routeurs. Un échec indique soit un problème d'adjacence OSPF, soit une instruction `network` manquante dans la config OSPF.

#### TestBFD — Pairs BFD

```
frr-rtr-01: vtysh -c "show bfd peers"  →  doit contenir "Status: Up"
```

Vérifie que tous les pairs BFD sont en état `Up` sur chaque routeur. BFD nécessite que les deux côtés soient configurés avec des timers correspondants.

#### TestConnectivity — Ping de bout en bout

```
docker exec clab-...-host-left ping -c 3 -W 2 192.168.40.10
docker exec clab-...-host-right ping -c 3 -W 2 192.168.10.10
```

Ping de `host-left` vers `host-right` et vice versa. Cela traverse les 4 routeurs et confirme que le plan de données complet fonctionne.

Teste également les pings loopback à loopback entre toutes les paires de routeurs, ce qui valide que les routes loopback sont correctement annoncées et installées.

#### TestSSoT — Audit de cohérence SSOT

C'est le test le plus distinctif de ce projet.

```python
# Interroger Infrahub : quelle zone OSPF chaque interface devrait-elle avoir ?
# Interroger FRR : quelle zone OSPF le routeur a-t-il réellement ?
# Comparer : s'ils diffèrent → ÉCHEC
```

`post_check.py` interroge l'API GraphQL d'Infrahub pour obtenir la zone OSPF **attendue** par interface, puis exécute `vtysh -c "show ip ospf interface"` sur chaque conteneur pour obtenir la zone OSPF **réelle**. Si elles diffèrent, le test échoue avec un message clair :

```
FAILED: frr-rtr-03/eth1 — SSOT says area=0, router has area=1
```

> **C'est le test clé.** Il fait échouer le pipeline dès que le réseau en production diverge du SSOT — qu'il s'agisse d'une modification manuelle, d'un bug dans la génération de config, ou d'un déploiement raté.

### CommonSetup — Attente de la convergence OSPF

Avant d'exécuter tout test, `post_check.py` attend la convergence OSPF :

```python
def wait_ospf_convergence(self, rtr01):
    converged = wait_for_ospf_full(rtr01.custom["container"], timeout=60)
    if not converged:
        self.skipped("OSPF not converged after 60 s", goto=["next_tc"])
    time.sleep(15)  # Attente supplémentaire : Full ≠ routes installées
```

Il y a deux phases dans la convergence OSPF :
1. **État Full des voisins** — adjacence établie, échange de LSA terminé
2. **Installation dans le RIB** — SPF calculé, routes installées dans le noyau

L'attente supplémentaire de 15 secondes est nécessaire car `Full` dans la table des voisins apparaît ~2–5 secondes avant que les routes soient dans la table de routage du noyau. La supprimer entraîne des échecs intermittents de `TestRouting`.

---

## 9. Le démo de panne SSOT

### Ce qu'il démontre

Le démo de panne répond à la question : **« Que se passe-t-il si le SSOT contient des données incorrectes ? »**

Il montre le cycle de vie complet :

```
[SSOT correct] → génération → déploiement → tests PASSENT
      ↓
[Mutation SSOT : zone 0 → zone 1 sur rtr-03/eth1]
      ↓
[Régénération config] → rechargement routeur → OSPF se casse
      ↓
[post_check ÉCHOUE : nombre de voisins, routage, ping, audit SSOT]
      ↓
[Restauration SSOT : zone 1 → zone 0]
      ↓
[Régénération config] → rechargement routeur → OSPF se rétablit
      ↓
[post_check PASSE]
```

### Lancer le démo

```bash
source .venv/bin/activate
INFRAHUB_TOKEN=satoken bash scripts/failure_demo.sh
```

### Déroulement étape par étape

Le démo exécute **8 étapes**, chacune journalisée avec un en-tête clair :

| Étape | Action | Résultat attendu |
|---|---|---|
| 1/8 | Vérifier la disponibilité d'Infrahub | Infrahub répond sur le port 8000 |
| 2/8 | Charger les données SSOT + générer les configs | `configs/frr-rtr-0X/frr.conf` écrit depuis Infrahub |
| 3/8 | Déployer le lab + vérifications baseline pre/post | **PASSE** — le réseau est correct |
| 4/8 | Lire la zone OSPF actuelle depuis Infrahub | Sauvegarde `original_area=0` pour le rollback |
| 5/8 | **Injection de panne** : régler `frr-rtr-03/eth1 ospf_area → 1` dans Infrahub | Le SSOT indique maintenant zone 1 |
| 5/8 | Régénérer la config frr-rtr-03 + rechargement (`vtysh -b`) | Le routeur est maintenant en zone 1 |
| 6/8 | Lancer post_check | **ÉCHOUE** — adjacence OSPF perdue, routage cassé, audit SSOT divergent |
| 7/8 | **Restauration** : régler `frr-rtr-03/eth1 ospf_area → 0` dans Infrahub | SSOT revient à zone 0 |
| 7/8 | Régénérer la config + rechargement | Routeur de retour en zone 0 |
| 8/8 | Lancer post_check | **PASSE** — rétablissement complet |

### Pourquoi l'incompatibilité de zone casse OSPF

Les routeurs OSPF ne forment des adjacences qu'avec des voisins dans la **même zone**. Si `rtr-03/eth1` est en zone 1 mais que `rtr-02/eth2` est en zone 0, leurs paquets Hello seront rejetés :

```
rtr-02 (zone 0) ←── eth2──eth1 ──→ rtr-03 (zone 1)
                         ✗ REJETÉ : incompatibilité de zone
```

La conséquence :
- rtr-02 perd son voisin avec rtr-03 → pas de routes au-delà de rtr-02
- rtr-04 perd son seul voisin → complètement isolé
- Le ping de host-left à host-right échoue (pas de route)

### Point d'attention : le SSOT n'est pas la seule couche

Le démo montre que même avec le SSOT restauré, le routeur doit également être rechargé. Le démo fait ceci :

```bash
# 1. Mettre à jour le SSOT
python scripts/set_ospf_area.py --device frr-rtr-03 --interface eth1 --area 0

# 2. Régénérer frr.conf depuis le SSOT
python scripts/generate_configs.py

# 3. Supprimer la config OSPF périmée de la config en cours (critique !)
docker exec clab-...-frr-rtr-03 vtysh \
    -c "configure terminal" \
    -c "interface eth1" \
    -c "no ip ospf area" \
    -c "end"

# 4. Recharger depuis le fichier (applique le frr.conf régénéré)
docker exec clab-...-frr-rtr-03 vtysh -b
```

L'étape 3 (`no ip ospf area`) est nécessaire car `vtysh -b` fusionne la config du fichier avec la config en cours — elle ne la remplace pas. Sans supprimer explicitement l'ancienne zone, le `ip ospf area 1` périmé resterait en place.

---

## 10. Comprendre le pipeline CI/CD

### Détail des stages

#### Stage `infrahub` — Démarrer le SSOT

Trois jobs (presque) parallèles :

| Job | Action |
|---|---|
| `infrahub_start` | `docker compose up -d` + attente de santé |
| `load_schema` | `infrahubctl schema load` (dépend de `infrahub_start`) |
| `load_data` | `python infrahub/load_data.py` (dépend de `load_schema`) |

Ces trois jobs ont des dépendances `needs:` pour garantir un ordre strict.

#### Stage `configure` — Générer les configs des équipements

| Job | Action |
|---|---|
| `generate_configs` | Interroge Infrahub GraphQL → écrit `configs/frr-rtr-0X/frr.conf` |

Après ce job, un `git diff configs/` montre exactement ce qui a changé par rapport aux configs commitées.

> Dans un workflow de **merge request** GitLab, vous pouvez configurer ce job pour publier le diff en commentaire sur la MR, offrant aux reviewers une visibilité exacte sur les lignes de config modifiées avant la fusion.

#### Stage `deploy`

| Job | Action |
|---|---|
| `deploy_lab` | `containerlab deploy -t topology.clab.yml --reconfigure` |

`--reconfigure` force une re-création complète même si la topologie tourne déjà (idempotent).

#### Stage `pre_check`

| Job | Action |
|---|---|
| `pre_check` | Lance `tests/pre_check.py` — conteneurs en marche, démons actifs, Infrahub accessible |

C'est une porte de sanité rapide. Si pre_check échoue, il est inutile d'attendre les 60 secondes de convergence OSPF dans post_check.

#### Stage `post_check`

| Job | Action |
|---|---|
| `post_check` | Lance `tests/post_check.py` — OSPF, routage, BFD, ping, audit SSOT |

C'est la **porte de qualité**. Si un test échoue, le pipeline est marqué échoué et la fusion est bloquée (si vous configurez des règles de protection de branche dans GitLab).

#### Stage `cleanup`

| Job | Action |
|---|---|
| `cleanup_lab` | `containerlab destroy --cleanup` + `docker compose down -v` |

Utilise `when: always` pour s'exécuter même si pre_check ou post_check a échoué, évitant les fuites de ressources sur le runner CI.

### Variables CI

Définies dans **GitLab → Paramètres → CI/CD → Variables** (ou dans le pipeline pour les démos) :

| Variable | Défaut | Description |
|---|---|---|
| `INFRAHUB_TOKEN` | `satoken` | Token API Infrahub |
| `INFRAHUB_ADDRESS` | `http://localhost:8000` | URL Infrahub (si différent de localhost) |

> En production, remplacez `satoken` par un token géré par un gestionnaire de secrets et marquez la variable comme **masquée** dans GitLab.

### Prérequis du runner

Le pipeline nécessite un runner avec **exécuteur shell** (pas Docker-in-Docker) avec :
- Accès au CLI Docker (pour exécuter `docker exec` sur les conteneurs Containerlab)
- Containerlab installé
- Le venv Python à `.venv/bin/activate`
- Tag : `frr-infrahub`

---

## 11. Référence des fichiers du projet

```
netalps_infrahub_public/
│
├── topology.clab.yml              # Topologie Containerlab — 4 routeurs FRR + 2 hôtes
│                                  # Définit les nœuds, liens, image, montages bind
│
├── .gitlab-ci.yml                 # Pipeline CI/CD complet en 6 stages
│
├── infrahub/
│   ├── .env.example               # Template de variables d'environnement (copier vers .env)
│   ├── docker-compose.yml         # Stack Infrahub : Neo4j + RabbitMQ + Redis + Infrahub
│   ├── schema/
│   │   └── network.yml            # Schéma personnalisé : NetalpsNetworkDevice + NetalpsInterface
│   └── load_data.py               # Bootstrap SSOT : pousse tous les équipements + interfaces dans Infrahub
│
├── configs/                       # Configs FRR (générées — ne pas modifier manuellement)
│   └── frr-rtr-0X/
│       ├── daemons                # Active ospfd, bfdd
│       ├── frr.conf               # Config de routage principale (OSPF, BFD, interfaces)
│       └── vtysh.conf             # Hostname vtysh
│
├── scripts/
│   ├── generate_configs.py        # Interroge Infrahub GraphQL → génère frr.conf par routeur
│   ├── set_ospf_area.py           # Lit ou écrit ospf_area dans Infrahub (utilisé par failure_demo)
│   ├── failure_demo.sh            # Scénario de panne/rétablissement SSOT de bout en bout (8 étapes)
│   └── wait_for_infrahub.sh       # Interroge /api/health jusqu'à ce qu'Infrahub soit prêt
│
└── tests/
    ├── testbed.yml                # Testbed pyATS : 6 équipements avec connexion docker exec
    ├── pre_check.py               # Étape 1 : conteneurs, démons, accessibilité Infrahub
    ├── post_check.py              # Étape 2 : OSPF, routage, BFD, ping, audit SSOT
    └── test_job.py                # Runner de job pyATS (enchaîne pre + post check)
```

---

## 12. Interface web Infrahub

Accédez à l'interface Infrahub sur **`http://localhost:8000`**

| Champ | Valeur |
|---|---|
| Login | `admin` |
| Mot de passe | `infrahub` |
| Token API | `satoken` |

### Que explorer

- **Objects → NetalpsNetworkDevice** — voir les 4 routeurs et les 2 hôtes
- **Objects → NetalpsInterface** — voir toutes les interfaces avec leurs attributs OSPF/BFD
- **Schema** — voir le modèle de données avec les types de champs et les contraintes
- **GraphQL Explorer** (`/graphql`) — exécuter directement dans le navigateur la requête de `generate_configs.py`

### Modifier une valeur manuellement

Essayez de changer `ospf_area` sur `frr-rtr-03/eth1` de `0` à `1` via l'interface, puis exécutez :

```bash
python scripts/generate_configs.py --device frr-rtr-03
git diff configs/frr-rtr-03/frr.conf
```

Vous verrez exactement une ligne modifiée dans la config générée — confirmant que le SSOT est la vraie source et que le fichier de config n'est qu'un artefact dérivé.

---

## 13. Dépannage

### Infrahub ne démarre pas

```bash
cd infrahub && docker compose logs --tail=50
```

Causes fréquentes :
- Neo4j trop lent au premier démarrage → attendre plus longtemps, relancer `wait_for_infrahub.sh`
- Port 8000 déjà utilisé → changer `INFRAHUB_PORT` dans `.env`

### `infrahubctl schema load` échoue avec `SchemaNotFound`

Infrahub n'est pas encore entièrement prêt. Relancer `wait_for_infrahub.sh` et réessayer.

### Les conteneurs FRR démarrent mais OSPF ne converge pas

```bash
# Vérifier les logs du démon FRR
docker exec clab-frr-infrahub-demo-frr-rtr-01 vtysh -c "show ip ospf neighbor"

# Vérifier si ospfd tourne
docker exec clab-frr-infrahub-demo-frr-rtr-01 ps aux | grep ospf

# Vérifier la frr.conf chargée
docker exec clab-frr-infrahub-demo-frr-rtr-01 vtysh -c "show running-config"
```

Cause fréquente : la config n'a pas été régénérée après un changement de schéma/données. Relancer `generate_configs.py`, puis `containerlab deploy --reconfigure`.

### `post_check.py` échoue sur TestRouting mais les voisins OSPF sont Full

C'est un problème de timing. Les voisins OSPF atteignent l'état `Full` 2–5 secondes avant que la table de routage du noyau ne soit mise à jour. Le `time.sleep(15)` dans `CommonSetup.wait_ospf_convergence` gère cela dans le test — mais si vous exécutez manuellement sans attendre, vous pouvez le rencontrer.

Solution : attendre ~20 secondes après l'apparition de `Full` avant d'exécuter le test.

### L'audit SSOT échoue après une modification manuelle de config

Si vous modifiez manuellement un `frr.conf` dans `configs/` et le redéployez, l'audit SSOT échouera car le SSOT contient toujours l'ancienne valeur. Toujours régénérer les configs depuis Infrahub — ne jamais modifier `frr.conf` directement.

---

## 14. Pour aller plus loin

Ce projet est un point de départ. Voici des pistes d'extension :

### Ajouter un peering BGP

Ajoutez un attribut `bgp_asn` à `NetalpsNetworkDevice` dans le schéma, renseignez-le dans `load_data.py`, et étendez `generate_configs.py` pour générer des blocs `router bgp <asn>`. Ajoutez ensuite un cas de test `TestBGP` dans `post_check.py`.

### OSPF Multi-Zone

Ajoutez un attribut `ospf_area` au niveau de l'équipement (pour les routeurs de bordure de zone), étendez le schéma, et modifiez `generate_configs.py` pour générer la config ABR correcte. L'audit SSOT dans `post_check.py` validerait alors les déploiements multi-zones.

### Infrahub Transforms

Au lieu du `generate_configs.py` Python personnalisé, utilisez les [Infrahub Transforms](https://docs.infrahub.app/guides/transform/) — une fonctionnalité intégrée d'Infrahub qui génère des templates Jinja2 côté serveur à partir de requêtes GraphQL. Cela rend la génération de config accessible via l'API sans script côté client.

### Diff de config sur MR GitLab

Étendez `generate_configs.py` pour produire un diff structuré, et ajoutez un job `.gitlab-ci.yml` qui le publie en commentaire de merge request via l'API GitLab. Les reviewers verront exactement quelles lignes de config la MR modifie.

### Étendre à d'autres fournisseurs

Remplacez ou ajoutez des nœuds Nokia SR Linux (supportés par Containerlab nativement). Ajoutez un champ `vendor` à `NetalpsNetworkDevice` et faites dispatcher `generate_configs.py` vers des générateurs spécifiques à chaque fournisseur.

---

## Licence

MIT — libre d'utilisation, de modification et de partage.

## Projets liés

- [netalps_demo](https://github.com/jeyriku/netalps_demo_public) — la version simplifiée à 2 routeurs dont ce projet est l'extension
- [Infrahub](https://github.com/opsmill/infrahub) — le SSOT open-source utilisé ici
- [Containerlab](https://github.com/srl-labs/containerlab) — le moteur de lab virtuel
- [pyATS](https://developer.cisco.com/pyats/) — le framework de test réseau de Cisco
