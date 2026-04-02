
from datetime import datetime
import uuid
from typing import List, Dict, Any, Optional
import json
from pathlib import Path

class QuestionTracker:
    """
    Tracks questions at document and section levels, their answers, and statuses.
    Persists state optionally for multi-session continuity.
    """
    def __init__(self, persist_path: Optional[str] = None):
        """
        Initialize the tracker.
        If persist_path is provided, load existing state or prepare to save.
        """
        self.questions: Dict[str, Dict[str, Any]] = {}  # question_id -> entry
        self.persist_path = Path(persist_path) if persist_path else None
        if self.persist_path and self.persist_path.exists():
            try:
                data = json.loads(self.persist_path.read_text(encoding='utf-8'))
                # Convert timestamps from ISO if needed
                for qid, entry in data.items():
                    # Parse datetime strings back to datetime objects if stored as ISO
                    entry['created_at'] = datetime.fromisoformat(entry['created_at'])
                    entry['updated_at'] = datetime.fromisoformat(entry['updated_at'])
                    # Answers timestamps
                    for ans in entry.get('answers', []):
                        ans['timestamp'] = datetime.fromisoformat(ans['timestamp'])
                    self.questions[qid] = entry
            except Exception:
                # If reading fails, start fresh
                self.questions = {}

    def _persist(self):
        """
        Save the current state to the persist_path as JSON with ISO timestamps.
        """
        if not self.persist_path:
            return
        serializable = {}
        for qid, entry in self.questions.items():
            e = entry.copy()
            # Convert datetimes to ISO strings
            e['created_at'] = e['created_at'].isoformat()
            e['updated_at'] = e['updated_at'].isoformat()
            # Answers timestamps
            ans_list = []
            for ans in e.get('answers', []):
                a = ans.copy()
                if isinstance(a.get('timestamp'), datetime):
                    a['timestamp'] = a['timestamp'].isoformat()
                ans_list.append(a)
            e['answers'] = ans_list
            serializable[qid] = e
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(serializable, indent=2), encoding='utf-8')
        except Exception:
            pass

    def add_question(self, question_text: str, level: str, section_path: Optional[str] = None) -> str:
        """
        Add a new question to track.
        level: 'document' or 'section'
        section_path: e.g., '1.2' for section-level questions
        Returns question_id
        """
        qid = str(uuid.uuid4())
        entry: Dict[str, Any] = {
            "question_id": qid,
            "level": level,
            "section_path": section_path,
            "question_text": question_text,
            "status": "open",
            "answers": [],  # list of {source_type, snippet, citation, timestamp}
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        self.questions[qid] = entry
        self._persist()
        return qid

    def record_answer(self, question_id: str, snippet: str, citation: Dict[str, Any], source_type: str):
        """
        Record an answer for a given question, marking it answered.
        """
        entry = self.questions.get(question_id)
        if not entry:
            return
        answer = {
            "source_type": source_type,
            "snippet": snippet,
            "citation": citation,
            "timestamp": datetime.utcnow()
        }
        entry.setdefault('answers', []).append(answer)
        entry['status'] = 'answered'
        entry['updated_at'] = datetime.utcnow()
        self._persist()

    def get_open_questions(self, level: Optional[str] = None, section_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieve open questions, optionally filtered by level and/or section_path.
        """
        results = []
        for entry in self.questions.values():
            if entry['status'] != 'open':
                continue
            if level and entry['level'] != level:
                continue
            if section_path and entry['section_path'] != section_path:
                continue
            results.append(entry)
        return results

    def get_question(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Get a question entry by ID."""
        return self.questions.get(question_id)

    def mark_deferred(self, question_id: str):
        """Mark a question as deferred if not answerable now."""
        entry = self.questions.get(question_id)
        if not entry:
            return
        entry['status'] = 'deferred'
        entry['updated_at'] = datetime.utcnow()
        self._persist()

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all question entries."""
        return list(self.questions.values())

    def get_answered_questions(self) -> List[Dict[str, Any]]:
        """Return questions marked as answered."""
        return [e for e in self.questions.values() if e['status'] == 'answered']

    def get_deferred_questions(self) -> List[Dict[str, Any]]:
        """Return questions marked as deferred."""
        return [e for e in self.questions.values() if e['status'] == 'deferred']

# Singleton instance for easy import
question_tracker = QuestionTracker(persist_path=".clericus/questions.json")