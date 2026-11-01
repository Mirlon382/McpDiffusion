# Démonstration — trois briques, une famille

## Le récit (30 secondes)

L’INSEE expose trois familles de données, chacune dans un serveur MCP autonome :

- **insee.fr** : publications, *Informations rapides*, chiffres-clés et indicateurs de la page d’accueil ;
- **MELODI** : catalogue de jeux de données, modalités et observations détaillées ;
- **RMES** : métadonnées RDF, définitions et nomenclatures — pas de chiffres ni d’observations.

On peut connecter un client directement à une brique, n’en déployer qu’un sous-ensemble, ou les réunir dans l’agrégat in-process. La passerelle ajoute un catalogue et le routage inter-briques. Elle ne remplace ni ne recalcule leurs résultats : pour une même requête, les outils directs, l’agrégat et la passerelle appellent la même logique source et retournent le même contenu structuré. Les noms vus à travers la passerelle sont préfixés par `insee_`, `melodi_` ou `rmes_`.

La démonstration suit cette question :

> Explorer l’IPC : publication, série détaillée, métadonnées.

## Coûts et limites à dire à voix haute

- **Trois limites de débit indépendantes.** Par défaut, chaque processus de brique a son propre plafond de 100 requêtes par minute. Ce n’est pas un quota familial unique : répartir les appels entre les trois serveurs consomme trois buckets.
- **Deux briques dépendent d’Elasticsearch.** insee.fr et MELODI ont chacun leur propre processus/client Elasticsearch, mais le déploiement compose leur fournit le même cluster. L’arrêt d’un processus ne coupe que ses outils ; la perte du cluster Elasticsearch rend indisponibles les outils de recherche des deux briques. RMES n’utilise pas Elasticsearch et reste indépendant.
- **Les retours opérateur vont à la passerelle.** `send_feedback` est possédé par la passerelle et consigné dans son journal, sans backend amont. Les briques ne publient pas cet outil.
- **Un index préconstruit n’est pas une promesse d’actualité.** Lors de l’exécution vérifiée ici, la recherche de publications a retourné des résultats de 2016 (voir ci-dessous). Les indicateurs d’accueil sont aussi des valeurs embarquées ; la démonstration porte sur la composition et le routage, pas sur la fraîcheur des chiffres.

## Pré-requis et démarrage

Procédure validée avec `uv`, Podman rootless et `podman-compose` lancé via `uvx`, depuis deux clones propres. Depuis un répertoire parent vide, reproduisez les révisions testées :

```bash
git clone --branch rework/settle-mcp-layer --single-branch https://github.com/Mirlon382/McpDiffusion.git McpDiffusion
git clone --branch main --single-branch https://github.com/Mirlon382/mcpgateway.git mcpgateway
git -C McpDiffusion checkout 3c7c92b25ce684e5fba5083f5c4f76ce1dc9909f
git -C mcpgateway checkout 3b5c265be18a9a30e1795e3d0c62e0d1b3513cc7
cd McpDiffusion
cp .env.example .env
uv sync
```

Dans un clone neuf, `cp .env.example .env` crée le fichier ; si `.env` existe déjà et contient une configuration, conservez-le au lieu de le remplacer. Depuis la racine de `McpDiffusion`, démarrez Elasticsearch, restaurez son snapshot, puis lancez les trois briques et l’agrégat :

```bash
uvx --from podman-compose podman-compose -p p8demo up --build elasticsearch es-restore insee-mcp melodi-mcp rmes-mcp mcpdiffusion
```

Les endpoints sont `http://127.0.0.1:8001/mcp` (insee.fr), `:8002/mcp` (MELODI), `:8003/mcp` (RMES) et `:8000/mcp` (agrégat). Attendez que les routes `/health` de ces quatre ports répondent avec `"status":"ready"`.

Dans un second terminal, depuis `McpDiffusion` :

```bash
cd ../mcpgateway
uv sync
uv run mcpgateway --registry ../McpDiffusion/deploy/gateway-demo.yaml \
  --host 127.0.0.1 --port 8100
```

La passerelle écoute sur `http://127.0.0.1:8100/mcp`. Le registre local regroupe les trois entrées sous le domaine `Insee` et ne suppose pas de DNS Docker : il cible les ports publiés sur `127.0.0.1`.

## Parcours live : quoi taper, quoi montrer

Dans un client MCP connecté à un endpoint, posez la question ci-dessus. Ou lancez le harnais, qui exécute le même parcours et vérifie l’égalité des résultats structurés : depuis la racine de `McpDiffusion` :

```bash
uv run python scripts/demo_split.py \
  --insee-url http://127.0.0.1:8001/mcp \
  --melodi-url http://127.0.0.1:8002/mcp \
  --rmes-url http://127.0.0.1:8003/mcp \
  --aggregate-url http://127.0.0.1:8000/mcp \
  --gateway-url http://127.0.0.1:8100/mcp
```

Le harnais montre d’abord l’outil d’accueil et une recherche de publication INSEE, puis découvre un jeu MELODI avant d’en lire trois observations, puis découvre le graphe RMES correspondant. Il répète le parcours par `search_tools` puis `call_tool` via le gateway. Une sortie vérifiée le 1er novembre 2026 comprenait notamment :

```text
INSEE brick → search_insee_conjoncture
  id 2017013 — « En mai 2016, les prix à la consommation baissent de 0,1 % sur un an »
Aggregate → search_insee_conjoncture (same returned data: yes)
MELODI brick → search_melodi_datasets
  dataset_id DS_IPCH
MELODI brick → get_melodi_observations
  dataset_id DS_IPCH, count 3
RMES brick → search_rmes_graphs
  total_graphs_matched 1 — http://rdf.insee.fr/graphes/produits
Gateway returned the same homepage data as the INSEE brick: yes
Gateway returned the same structured data as each brick: yes
```

Les résultats complets restent ceux de la vraie réponse : le script tronque seulement l’affichage à deux résultats de recherche et trois observations pour garder la séance lisible.

### Prouver que chaque brique est autonome

Arrêtez le gateway dans son terminal (`Ctrl-C`), gardez Elasticsearch en marche, puis testez une brique à la fois. Chaque appel direct ci-dessous a réussi depuis les clones propres, gateway et agrégat arrêtés, avec les deux autres processus de brique arrêtés :

```bash
uvx --from podman-compose podman-compose -p p8demo stop mcpdiffusion melodi-mcp rmes-mcp
uvx --from podman-compose podman-compose -p p8demo start insee-mcp
uv run fastmcp call http://127.0.0.1:8001/mcp get_insee_homepage --json
uvx --from podman-compose podman-compose -p p8demo stop insee-mcp
uvx --from podman-compose podman-compose -p p8demo start melodi-mcp
uv run fastmcp call http://127.0.0.1:8002/mcp search_melodi_datasets query='indice des prix a la consommation' number_of_datasets=1 --json
uvx --from podman-compose podman-compose -p p8demo stop melodi-mcp
uvx --from podman-compose podman-compose -p p8demo start rmes-mcp
uv run fastmcp call http://127.0.0.1:8003/mcp search_rmes_graphs graph_uri_substring=produits --json
```

Après chaque `start`, attendez que le `/health` de la brique retourne `"status":"ready"` avant l’appel client.

insee.fr et MELODI ont besoin d’Elasticsearch pour leurs outils de recherche ; leur outil `get_insee_homepage` ne le nécessite pas. RMES ne dépend que du endpoint SPARQL public.

### Prouver que l’agrégat n’a pas besoin des serveurs HTTP des briques

Gateway arrêté, laissez Elasticsearch et l’agrégat tourner, puis arrêtez les trois conteneurs autonomes. Les deux appels ont réussi avec ces conteneurs et le gateway arrêtés :

```bash
uvx --from podman-compose podman-compose -p p8demo stop insee-mcp melodi-mcp rmes-mcp
uvx --from podman-compose podman-compose -p p8demo start mcpdiffusion
uv run fastmcp call http://127.0.0.1:8000/mcp get_insee_homepage --json
uv run fastmcp call http://127.0.0.1:8000/mcp search_rmes_graphs graph_uri_substring=produits --json
```

Les deux appels ont réussi avec les conteneurs `insee-mcp`, `melodi-mcp` et `rmes-mcp` arrêtés. L’agrégat monte les applications des briques dans son propre processus ; il ne relaie pas vers leurs ports HTTP.

## Arrêt volontaire d’une brique

Après la preuve d’autonomie, relancez les briques autonomes et le gateway. Attendez que les quatre routes `/health` soient `ready` avant de faire l’arrêt :

Depuis `McpDiffusion` :

```bash
uvx --from podman-compose podman-compose -p p8demo start insee-mcp melodi-mcp rmes-mcp
```

Dans un second terminal, depuis `McpDiffusion`, démarrez le gateway et laissez-le tourner :

```bash
cd ../mcpgateway
uv sync
uv run mcpgateway --registry ../McpDiffusion/deploy/gateway-demo.yaml --host 127.0.0.1 --port 8100
```

Pour montrer le domaine de panne d’un processus, laissez les autres serveurs démarrés et arrêtez seulement insee.fr :

```bash
uvx --from podman-compose podman-compose -p p8demo stop insee-mcp
uv run python scripts/demo_split.py \
  --insee-url http://127.0.0.1:8001/mcp \
  --melodi-url http://127.0.0.1:8002/mcp \
  --rmes-url http://127.0.0.1:8003/mcp \
  --aggregate-url http://127.0.0.1:8000/mcp \
  --gateway-url http://127.0.0.1:8100/mcp \
  --failure-demo
```

Résultat réellement observé : l’outil INSEE n’est plus exposé par la découverte du gateway ; `search_rmes_graphs` répond toujours via le même gateway. Un client direct sur `8001` échoue également. L’agrégat en processus est distinct : il conserve ses propres applications montées tant que son processus et ses propres backends sont disponibles.

## Retour opérateur

`send_feedback` appartient au gateway, pas aux briques. Avec la recherche d’outils activée, découvrez-le via `search_tools`, puis appelez `call_tool` ; le gateway journalise le rapport et ne dépend pas d’un service amont pour l’enregistrer. Les deux appels suivants ont été exécutés pendant que la brique INSEE était arrêtée :

```bash
uv run fastmcp call http://127.0.0.1:8100/mcp search_tools query='send feedback report to gateway operators' --json
uv run fastmcp call http://127.0.0.1:8100/mcp call_tool name=send_feedback arguments='{"server":"insee","author":"p8-demo","feedback":"Walkthrough smoke test: feedback is owned by the gateway."}' --json
```

Le second appel a répondu `{"status":"success","message":"Feedback recorded successfully.","timestamp":"2026-11-01T20:58:20.117811Z"}`.

Pour arrêter la démonstration, arrêtez le processus du gateway (Ctrl-C), puis, depuis `McpDiffusion` :

```bash
uvx --from podman-compose podman-compose -p p8demo down -v
```

`-v` supprime le volume Elasticsearch propre au projet de démonstration. Lors de la validation, `podman-compose` a affiché un message d’erreur non bloquant pour `p8demo_inspector_1` (service non démarré) ; la commande a renvoyé 0, supprimé tous les conteneurs `p8demo` et retiré le volume `p8demo_elasticsearch-data`.

## Note sur la reproductibilité

La validation de bout en bout de cette version a été exécutée depuis deux clones propres, McpDiffusion `3c7c92b25ce684e5fba5083f5c4f76ce1dc9909f` et McpGateway `3b5c265be18a9a30e1795e3d0c62e0d1b3513cc7`. `uv sync` a réussi dans les deux ; Compose a restauré le snapshot et les quatre routes `/health` ont indiqué `ready`. Le harnais s’est terminé avec le code 0 et a confirmé l’égalité des données structurées directes, agrégées et routées pour les résultats INSEE, MELODI et RMES. Les appels directs aux trois briques ont aussi réussi avec les autres processus de brique arrêtés ; les appels à l’agrégat ont réussi avec les trois conteneurs autonomes arrêtés. Après l’arrêt d’INSEE, le gateway a omis son outil dans `search_tools` tandis que RMES restait appelable ; le retour opérateur a répondu avec succès alors qu’INSEE était arrêté. La publication obtenue dans ce snapshot date de mai 2016 : la démo montre la composition, pas la fraîcheur des données.
