from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import QThread, pyqtSignal
from pymongo import MongoClient

from application.config import (
    CHECKPOINT_COLLECTION,
    CHECKPOINT_ID,
    COLLECTION,
    DB_NAME,
    MONGO_BATCH_SIZE,
    MONGO_URI,
)



class MongoLoader(QThread):
    """Charge les entreprises sans LinkedIn depuis MongoDB avec leurs données complètes."""
    done    = pyqtSignal(list, int)
    error   = pyqtSignal(str)
    log     = pyqtSignal(str)

    def __init__(self, batch: int = MONGO_BATCH_SIZE):
        super().__init__()
        self.batch = batch

    def run(self):
        client = None
        try:
            self.log.emit("🔌 Connexion à MongoDB…")
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10_000)
            db  = client[DB_NAME]
            col = db[COLLECTION]
            progress_col = db[CHECKPOINT_COLLECTION]

            checkpoint = progress_col.find_one({"_id": CHECKPOINT_ID}) or {}
            after_id = checkpoint.get("last_id")
            if checkpoint.get("status") == "complete":
                after_id = None

            missing_link_query = {
                "$or": [
                    {"socialAccounts": {}},
                    {"socialAccounts": {"$exists": False}},
                    {"socialAccounts.linkedin": {"$exists": False}},
                    {"socialAccounts.linkedin": None},
                    {"socialAccounts.linkedin": []},
                    {"socialAccounts.linkedin": ""},
                ]
            }

            query = missing_link_query
            if after_id is not None:
                query = {
                    "$and": [
                        missing_link_query,
                        {"_id": {"$gt": after_id}},
                    ]
                }

            total = col.count_documents(query)
            self.log.emit(f"📋 {total:,} entreprises restantes à analyser")

            self.log.emit(f"⬇️  Chargement de {self.batch} entreprises pour continuer…")
            projection = {
                "_id": 1, "companyName": 1, "tradeName": 1,
                "url": 1, "domains": 1, "socialAccounts": 1,
                "countryCode": 1, "location": 1, "street": 1,
                "streetName": 1, "streetNumber": 1, "zip": 1,
                "region": 1, "description": 1, "resultsSignals": 1,
                "resultsWebsite": 1, "status": 1
            }
            cursor = col.find(query, projection).sort("_id", 1).limit(self.batch)

            companies = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                companies.append(doc)

            if not companies:
                progress_col.update_one(
                    {"_id": CHECKPOINT_ID},
                    {
                        "$set": {
                            "status": "complete",
                            "completed_at": datetime.now(timezone.utc),
                        }
                    },
                    upsert=True,
                )

            self.log.emit(f"✅ {len(companies)} entreprises chargées avec succès.")
            self.done.emit(companies, total)

        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if client is not None:
                client.close()
