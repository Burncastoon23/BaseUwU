# Agent Registry

Registre de capacités d'agents IA — cartes lisibles par l'humain **et** par la machine, catalogue SKU, vérification continue, API REST et client Android.

> L'ancienne bibliothèque C « BaseUwU » (encodage binaire→texte) vit désormais dans [`legacy/`](legacy/).

## Composants

| Répertoire | Rôle |
|---|---|
| `registry/` | Modèles (AgentCard, capacités, TrustLevel), SKU, consolidation, fusion, persistance SQLite |
| `verifier/` | Probes de vérification, suite d'évaluation continue, scheduler TTL |
| `api/` | Serveur REST (stdlib, zéro dépendance), auth par clé API |
| `agents/` | Agents d'exemple |
| `android/` | Client Android (Kotlin, OkHttp, Material3) |
| `tests/` | Suite `unittest` |
| `cli.py` | CLI : list, show, verify, drift, ingest-mcp, ingest-a2a, keygen |

## Démarrage rapide

```bash
# Serveur (aucune dépendance à installer, Python ≥ 3.11)
python api/start.py --port 8080
# État persisté dans data/registry.db (configurable: --db ou $REGISTRY_DB)

curl localhost:8080/health
curl localhost:8080/agents
curl localhost:8080/sku
```

### Docker

```bash
docker build -t agent-registry .
docker run -p 8080:8080 -v registry-data:/data agent-registry
```

### Sécurité

Sans clé configurée, l'API démarre en mode ouvert (warning au boot). En production :

```bash
python cli.py keygen admin           # génère une clé
export REGISTRY_API_KEYS="admin:<clé>"
python api/start.py --host 0.0.0.0
```

Les GET restent publics (sauf `REGISTRY_REQUIRE_READ_KEY=1`) ; POST/DELETE exigent une clé admin via l'en-tête `X-API-Key`. CORS configurable par `REGISTRY_CORS_ORIGINS`.

## SKU

Chaque agent reçoit un code stable `{CATÉGORIE}-{SOUS-CAT}-{HASH}` (ex. `CODE-WRITE_CO-61a7`). Le niveau de confiance (VRF/DCL/UNK) est un attribut **mutable** — la re-vérification ne change jamais le code. Les anciens codes (format historique à 4 segments) restent résolubles via des alias (`resolved_from` dans la réponse).

## API

```
GET    /health                        état + compteurs
GET    /agents                        liste des agents
POST   /agents                        enregistrer un agent (admin)
DELETE /agents/{id}                   supprimer (admin)
GET    /agents/obsolete               candidats à suppression
POST   /agents/consolidate?dry_run=   passe de consolidation (admin)
POST   /agents/refresh                re-vérification async (admin)
POST   /agents/merge                  fusion N→1 (admin)
POST   /agents/{id}/verify            probes + mise à jour trust (admin)
GET    /sku                           catalogue actif
GET    /sku/{code}                    détail (suit les alias)
GET    /sku/{code}/agent              AgentCard via SKU
GET    /sku/search?q=&category=&tier=
GET    /sku/catalog                   catalogue complet + meta
POST   /sku/sync                      resynchronisation (admin)
DELETE /sku/{code}                    désactivation (admin)
```

## Tests

```bash
python -m unittest discover -s tests
```

## Android

```bash
cd android && ./gradlew assembleDebug
```

L'URL du serveur et la clé API se configurent dans l'écran Settings de l'app.
