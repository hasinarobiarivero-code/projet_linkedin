# LinkedIn Auto-Enricher — Leadfeeder (Haute Précision & Thème Blanc)

Application PyQt6 en **thème blanc moderne** avec **analyse de données de haute précision** pour éliminer les faux positifs et n'associer que les profils LinkedIn véritablement légitimes.

---

## 🎯 Amélioration Majeure : Analyse de Données & Filtre Anti-Faux Positifs

Auparavant, la recherche pouvait attribuer des profils LinkedIn complètement hors sujet (ex: une page américaine comme *Wall Street Oasis* pour une SARL française *Oasis Anjou*, ou *Fuel Scam Alert* pour *Scam Lyon*) simplement parce qu'un mot générique correspondait.

### Le nouveau moteur d'analyse applique 4 filtres stricts :

1. **F1-Score sur les mots distinctifs du nom** :
   - Ignore les termes juridiques (*SARL, SAS, SCI, EURL, SA, Ltd...*) et les mots vides (*de, la, le, du, et...*).
   - Le titre de l'entreprise doit obtenir un F1 d'au moins 65% ; le slug ne remplace le titre qu'en cas d'absence de celui-ci.
2. **Contrôle Géographique Strict & Rejet Étranger** :
   - Pour les entreprises basées en France (`FR`), un profil mentionnant explicitement un pays étranger (*USA, Inde, UK, Californie, etc.*) sans attache en France est pénalisé (-40 points).
   - Bonus de validation si la ville (*Paris, Lyon, Marseille, Sèvres, etc.*) ou le département correspond.
3. **Validation Croisée des Noms de Domaine** :
   - Si l'entreprise possède un site internet dans MongoDB, le nom de domaine est comparé au slug LinkedIn pour garantir une correspondance à 100%.
4. **Seuil strict de validation (65% minimum)** :
   - Le nom affiché est comparé en priorité au nom de l'entreprise ; le slug LinkedIn ne sert qu'en l'absence de titre.
   - Une correspondance partielle n'est retenue qu'avec un domaine concordant. Les résultats sans titre ne reprennent jamais automatiquement le nom recherché.
   - Si les résultats trouvés sur LinkedIn sont trop éloignés ou douteux, l'application les classe en **`Non trouvé`** plutôt que d'associer une fausse entreprise.

---

## 🎛️ Contrôles de l'Interface

- Au lancement, LinkedIn s'ouvre dans Chrome à droite et le terminal de l'application reste visible à gauche. Le scraping commence uniquement après le clic sur **« Lancer »**.
- **`Mode : 🌐 Recherche Web Google (Sans compte LinkedIn)`** : Recherche immédiate sans aucun identifiant ni mot de passe !
- **`Mode : 🔒 LinkedIn Direct`** : Recherche directe sur LinkedIn pour les utilisateurs connectés.
- Le mode choisi est mémorisé et restauré au prochain démarrage. En mode direct, connectez-vous dans la fenêtre Chrome si nécessaire.
- **« Lancer / reprendre »** : Analyse automatiquement toutes les entreprises sans lien LinkedIn dans MongoDB, sans demander de démarrer chaque bloc. Les blocs sont internes à l'application et une progression globale est affichée. Les profils validés (lien, nom et ressemblance) sont écrits directement dans `socialAccounts.linkedin` de `adding_social_accounts`. La recherche ne modifie pas `linkedin_results.json` ; son contenu existant est conservé. Les liens déjà présents ne sont pas remplacés.
- Après chaque entreprise traitée, l'identifiant de reprise est enregistré dans la collection MongoDB `linkedin_enrichment_progress`. Après une fermeture ou une coupure, cliquez sur **« Lancer / reprendre »** pour continuer après le dernier identifiant confirmé. Les entreprises déjà liées sont ignorées ; celles sans résultat valide pourront être réessayées lors d'une nouvelle analyse complète.

Le calcul du pourcentage de ressemblance et les fonctions de nettoyage associées sont dans `matching.py`. Pour le réutiliser : `from matching import calculate_precision_resemblance`, puis appeler `calculate_precision_resemblance(candidat, entreprise)`. La fonction retourne le score (de 0 à 100) et un dictionnaire de détails de validation.

Dans `linkedin_results.json`, chaque entreprise contient `linkedin`, une liste de profils avec `link`, `name` et `resemblance` (pourcentage), ainsi que `linkedinStatus` (`TROUVE` ou `NON TROUVE`). Un profil avec 0 % de ressemblance est exclu de la liste et son lien n'est pas affiché. Les nouveaux résultats de la recherche lancée par « Lancer » sont enregistrés uniquement dans MongoDB.

Les fichiers `config.json`, `linkedin_results.json` et le profil Chrome sont chargés depuis le dossier de l'application, même si elle est lancée depuis un autre répertoire.

---

## 🚀 Lancement

```powershell
python main.py
```
# projet_linkedin
"# projet_linkedin" 
