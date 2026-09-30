# Audit local des vidéos eCoach — 30 septembre 2026

Périmètre : dix vidéos distinctes fournies par l’opérateur, accessibles dans Downloads. Le doublon 8872… (1) n’est pas compté deux fois. Aucun accès aux rapports du serveur.

Méthode : balayage visuel à quatre images par seconde des dix vidéos avec les détecteurs précédents, inspection d’images représentatives, puis vérification des détecteurs corrigés sur 40 images extraites. Cette dernière vérification isole la décision visuelle (OCR neutralisé) : elle ne remplace pas une réanalyse complète en production.

## Règle métier confirmée

Une seule coche suffit, quelle que soit l’opération eCoach. Data peut rester vide. Une coche de sélection peut être visible pendant un chargement : cette règle valide alors la preuve, sans démontrer que toutes les opérations sont terminées. Une couleur verte, une case vide ou une animation seule ne suffisent pas.

## Résultats sur les images testées après correction

| Vidéo (préfixe UUID) | Application | Images positives / testées |
|---|---|---|
| 0aff | PFNLCoach | 2 / 5 |
| 42ff | PFNLCoach | 4 / 5 |
| 50bf | FinanceCoach | 4 / 5 |
| 5e96 | FinanceCoach | 5 / 6 |
| 7a45 | YEBCoach | 1 / 1 |
| 8713 | FinanceCoach | 1 / 1 |
| 8872 | FinanceCoach | 4 / 6 |
| 9245 | FinanceCoach | 5 / 5 |
| c6c1 | FinanceCoach | 1 / 1 |
| e91b | AgriCoach | 5 / 5 |

Chaque vidéo a au moins une image reconnue. Les images négatives incluent des menus d’accueil et notifications : elles ne doivent pas devenir positives artificiellement.

## Corrections de cet audit

- FinanceCoach : prise en compte de la coche bleue dans la case, sans attendre le petit badge vert.
- Début de vidéo inclus dans la décision chronologique (YEBCoach revient à l’accueil après environ une seconde).
- YEBCoach : retrait de la bande noire latérale Android avant recherche des cases.
- Notifications Bluetooth avec « Échec de 0 élément » ignorées lorsqu’elles appartiennent clairement au panneau Android, même sans libellé d’enregistrement.
- Détection des coches vertes : correction d’une variable de coordonnées réutilisée par erreur pendant l’analyse des composants blancs.

## Limites restantes

- Test local de 73 cas, sans exécution de l’OCR complet ni des appels IA sur ces dix vidéos.
- Une erreur explicite de synchronisation ultérieure reste prioritaire. Un OCR erroné peut encore nécessiter un contrôle manuel.
- Les mises en page inconnues, très floues ou tournées ne sont pas garanties. Le balayage dense spécifique reste limité à FinanceCoach ; les autres applications utilisent les images extraites ordinaires.
- La reconnaissance de la coche ne corrige pas les identifiants ou dates OCR. Ne pas inventer l’année ni assimiler FR/MO/DYU à l’agent.
- Les anciennes décisions doivent être réanalysées après déploiement ; aucun rapport ni message WhatsApp n’a été modifié pendant cet audit.
