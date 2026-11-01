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

Cette procédure a été exécutée avec `uv`, Podman rootless et `podman-compose` lancé via `uvx`. Le compose du dépôt démarre Elasticsearch, restaure son snapshot, puis lance les trois briques et l’agrégat. Sur un premier clone, créez `.env` à partir de `.env.example` avant de lancer Compose ; ne remplacez pas un `.env` déjà présent. Le dépôt du gateway doit être disponible dans un checkout voisin nommé `../mcpgateway`, avec les changements P5/P6 qui ajoutent les trois briques et `send_feedback`.

Depuis la racine de `McpDiffusion` :

```bash
uv sync
uvx --from podman-compose podman-compose -p p8demo up --build \
  elasticsearch es-restore insee-mcp melodi-mcp rmes-mcp mcpdiffusion
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

Laissez Elasticsearch en marche, arrêtez l’agrégat, le gateway et les deux autres processus de brique, puis lancez une seule brique à la fois. Ces appels directs ont été exécutés avec les deux autres processus de brique arrêtés ; chacun a répondu avec son propre backend déclaré `ready` :

```bash
uv run fastmcp call http://127.0.0.1:8001/mcp get_insee_homepage --json
uv run fastmcp call http://127.0.0.1:8002/mcp search_melodi_datasets query='indice des prix a la consommation' number_of_datasets=1 --json
uv run fastmcp call http://127.0.0.1:8003/mcp search_rmes_graphs graph_uri_substring=produits --json
```

insee.fr et MELODI ont besoin d’Elasticsearch pour leurs outils de recherche ; leur outil `get_insee_homepage` ne le nécessite pas. RMES ne dépend que du endpoint SPARQL public.

### Prouver que l’agrégat n’a pas besoin des serveurs HTTP des briques

Arrêtez les trois services de brique, laissez uniquement Elasticsearch et l’agrégat, puis appelez les mêmes outils sur le port 8000 :

```bash
uv run fastmcp call http://127.0.0.1:8000/mcp get_insee_homepage --json
uv run fastmcp call http://127.0.0.1:8000/mcp search_rmes_graphs graph_uri_substring=produits --json
```

Les deux appels ont réussi avec les conteneurs `insee-mcp`, `melodi-mcp` et `rmes-mcp` arrêtés. L’agrégat monte les applications des briques dans son propre processus ; il ne relaie pas vers leurs ports HTTP.

## Arrêt volontaire d’une brique

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

Pour arrêter la démonstration, arrêtez le processus du gateway (Ctrl-C), puis, depuis `McpDiffusion` :

```bash
uvx --from podman-compose podman-compose -p p8demo down -v
```

`-v` supprime le volume Elasticsearch propre au projet de démonstration.

## Note sur la reproductibilité

La validation de bout en bout a utilisé le working tree courant de McpDiffusion et le working tree courant de McpGateway. Les changements de split et les changements P5/P6 du gateway ne sont pas encore disponibles comme deux révisions propres clonables ; le parcours a donc été réellement exécuté, mais pas depuis un clone vierge. Une fois ces changements publiés, rejouer les commandes ci-dessus depuis deux checkouts adjacents vérifiera la condition « clean clone » sans changer le scénario.
