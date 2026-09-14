"""Test réel d'une seule relance via l'API, avec le compte de l'opérateur."""
import getpass

import httpx

API_URL = "https://ges50.yingr-ai.com/api"


def run():
    email = input("Email de connexion à GES G50 : ").strip()
    password = getpass.getpass("Mot de passe (masqué) : ")
    with httpx.Client(base_url=API_URL, timeout=30) as client:
        response = client.post("/auth/login", json={"email": email, "password": password})
        del password
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        offset = 0
        selected = None
        while selected is None:
            response = client.get("/followups", params={"state": "OPEN", "offset": offset, "limit": 50})
            response.raise_for_status()
            page = response.json()
            for task in page["items"]:
                if task["messages"] or not task["recipient"]:
                    continue
                evidence_response = client.get(f"/evidence/{task['evidence_id']}")
                evidence_response.raise_for_status()
                evidence = evidence_response.json()
                if (evidence.get("extraction") or {}).get("sync_status") == "UNCONFIRMED":
                    selected = task
                    break
            offset += 50
            if offset >= page["total"]:
                break
        if selected is None:
            print("Aucun rapport non confirmé sans ancienne relance et avec destinataire. Aucun envoi.")
            return 2
        print("Rapport :", selected["filename"])
        print("Dossier :", selected["id"])
        print("Envoi d'une seule relance réelle, avec le message prévu par l'application…")
        try:
            response = client.post("/followups/send", json={"followup_ids": [selected["id"]]}, timeout=45)
            response.raise_for_status()
        except httpx.TimeoutException:
            print("Délai dépassé : résultat incertain. Vérifiez l'historique et WhatsApp sans renvoyer.")
            return 3
        except httpx.HTTPStatusError as exc:
            print("API : HTTP", exc.response.status_code)
            print("Envoi non confirmé. Vérifiez l'historique du dossier avant toute nouvelle tentative.")
            return 3
        result = response.json()
        if len(result) == 1 and result[0].get("id") == selected["id"] and result[0].get("status") == "SENT":
            print("SUCCÈS : une relance confirmée par la passerelle et enregistrée dans l'historique.")
            print("La réception/lecture par l'agent et le retour d'un rapport exploitable restent à vérifier.")
            return 0
        print("ENVOI NON CONFIRMÉ. Vérifiez WhatsApp et les logs Echec /control/send. Aucun nouvel essai automatique.")
        return 3


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except httpx.HTTPStatusError as exc:
        print("Accès API refusé ou indisponible : HTTP", exc.response.status_code)
        raise SystemExit(1) from None
    except httpx.RequestError:
        print("Connexion interrompue. Vérifiez l'historique avant de relancer le test.")
        raise SystemExit(1) from None
