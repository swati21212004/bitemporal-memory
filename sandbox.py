"""
🧠 Bitemporal Memory System — Interactive CLI Sandbox

This script provides a zero-dependency, fully-functional local demonstration
of the system's core capabilities:
- Write path with duplicate detection and PII filtering
- Contradiction detection and manual resolution
- Hybrid retrieval with logarithmic decay scoring
- Bitemporal snapshot queries & version history
- Interactive CLI prompt for rapid testing!

Run it with: python sandbox.py
"""

from __future__ import annotations

import math
import uuid
import re
from datetime import datetime, timedelta, timezone

# ── Colors & Emoji Helpers ───────────────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(title: str):
    print(f"\n{BOLD}{CYAN}=== {title} ==={RESET}\n")

# ── Simulated InMemory Database & Vector Similarity ──────────────────────────
class MockMemory:
    def __init__(
        self,
        content: str,
        memory_type: str,
        importance: float,
        tags: list[str],
        source: str,
        valid_from: datetime | None = None
    ):
        self.id = uuid.uuid4()
        self.content = content
        self.memory_type = memory_type
        self.importance = importance
        self.tags = tags or []
        self.source = source or "conversation"
        
        self.access_count = 0
        self.last_accessed_at = datetime.now(timezone.utc)
        self.decay_score = importance
        
        self.created_at = datetime.now(timezone.utc)
        self.superseded_at: datetime | None = None
        self.valid_from = valid_from or datetime.now(timezone.utc)
        self.valid_to: datetime | None = None
        
        self.is_deleted = False
        self.deleted_at: datetime | None = None
        self.supersedes_id: uuid.UUID | None = None

    def calculate_decay(self, current_time: datetime | None = None) -> float:
        if not current_time:
            current_time = datetime.now(timezone.utc)
        age_seconds = (current_time - self.last_accessed_at).total_seconds()
        age_days = max(0.0, age_seconds / 86400.0)
        # Logarithmic decay curve: importance * 1/(1 + ln(1 + age_days))
        self.decay_score = self.importance * (1.0 / (1.0 + math.log(1.0 + age_days)))
        return self.decay_score

    def access(self):
        self.access_count += 1
        self.last_accessed_at = datetime.now(timezone.utc)
        self.decay_score = self.importance

# Simplified bag-of-words cosine similarity for standalone sandbox usage
def get_cosine_similarity(text1: str, text2: str) -> float:
    def get_words(text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    words1 = get_words(text1)
    words2 = get_words(text2)
    
    vocab = set(words1 + words2)
    if not vocab:
        return 0.0

    vector1 = [words1.count(w) for w in vocab]
    vector2 = [words2.count(w) for w in vocab]
    
    dot_product = sum(v1 * v2 for v1, v2 in zip(vector1, vector2))
    mag1 = math.sqrt(sum(v ** 2 for v in vector1))
    mag2 = math.sqrt(sum(v ** 2 for v in vector2))
    
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)

class SandboxMemorySystem:
    def __init__(self):
        self.memories: list[MockMemory] = []
        self.audit_log: list[dict] = []
        self.initialize_default_memories()

    def initialize_default_memories(self):
        # 1. Active semantic memory
        m1 = MockMemory(
            content="User prefers using VS Code with vim keybindings",
            memory_type="procedural",
            importance=0.9,
            tags=["editor", "vim"],
            source="user_explicit"
        )
        # Backdate access of m1 to show decay
        m1.created_at = datetime.now(timezone.utc) - timedelta(days=7)
        m1.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=7)
        m1.calculate_decay()
        
        # 2. Active episodic memory
        m2 = MockMemory(
            content="User is building a high-performance vector search database",
            memory_type="episodic",
            importance=0.8,
            tags=["projects", "database"],
            source="conversation"
        )
        
        # 3. Superseded memory (historic state)
        m3_old = MockMemory(
            content="User prefers using PyCharm editor",
            memory_type="semantic",
            importance=0.7,
            tags=["editor"],
            source="conversation"
        )
        m3_old.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        m3_old.superseded_at = datetime.now(timezone.utc) - timedelta(days=7)
        m3_old.valid_to = datetime.now(timezone.utc) - timedelta(days=7)
        
        m1.supersedes_id = m3_old.id

        self.memories.extend([m1, m2, m3_old])

    def scan_pii(self, text: str) -> list[str]:
        found_pii = []
        if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", text):
            found_pii.append("Email Address")
        if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
            found_pii.append("Social Security Number (SSN)")
        if re.search(r"(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14})", text.replace(" ", "")):
            found_pii.append("Credit Card Number")
        if re.search(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text):
            found_pii.append("Phone Number")
        return found_pii

    def write_memory(
        self,
        content: str,
        memory_type: str = "semantic",
        importance: float = 0.5,
        tags: list[str] = None,
        source: str = "conversation"
    ) -> tuple[str, MockMemory | tuple[MockMemory, float] | None]:
        # 1. PII Gate Check
        pii_found = self.scan_pii(content)
        if pii_found:
            print(f"{YELLOW}⚠️  [PII Warning] Detected sensitive details: {', '.join(pii_found)}{RESET}")

        # 2. Duplicate and Contradiction detection
        active_memories = [m for m in self.memories if not m.is_deleted and not m.superseded_at]
        for existing in active_memories:
            similarity = get_cosine_similarity(content, existing.content)
            
            # Exact duplicate rejection
            if similarity > 0.95:
                return "DUPLICATE", existing
                
            # Contradiction flag (high similarity but potentially divergent meanings)
            # Standalone sandbox triggers contradiction based on negative keyword changes 
            # like 'not', 'don\'t', 'doesn\'t' or changing names
            if similarity > 0.65:
                neg_existing = any(w in existing.content.lower() for w in ["not", "never", "don't", "dislike"])
                neg_new = any(w in content.lower() for w in ["not", "never", "don't", "dislike"])
                if neg_existing != neg_new or len(set(content.split()) ^ set(existing.content.split())) > 2:
                    return "CONTRADICTION", (existing, similarity)

        # 3. Safe Write
        new_mem = MockMemory(
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=tags or [],
            source=source
        )
        self.memories.append(new_mem)
        self.audit_log.append({
            "id": uuid.uuid4(),
            "memory_id": new_mem.id,
            "action": "create",
            "performed_at": datetime.now(timezone.utc)
        })
        return "SUCCESS", new_mem

    def resolve_contradiction(self, old_id: uuid.UUID, new_content: str, action: str):
        old_mem = next((m for m in self.memories if m.id == old_id), None)
        if not old_mem:
            return False
            
        if action == "supersede":
            now = datetime.now(timezone.utc)
            old_mem.superseded_at = now
            old_mem.valid_to = now
            
            _, new_mem = self.write_memory(
                content=new_content,
                memory_type=old_mem.memory_type,
                importance=old_mem.importance,
                tags=old_mem.tags,
                source="user_resolved"
            )
            if new_mem and isinstance(new_mem, MockMemory):
                new_mem.supersedes_id = old_mem.id
                
            self.audit_log.append({
                "id": uuid.uuid4(),
                "memory_id": old_mem.id,
                "action": "supersede",
                "performed_at": now
            })
            return True
            
        elif action == "keep_both":
            self.write_memory(content=new_content)
            return True
        return False

    def retrieve_memories(self, query: str, top_k: int = 5) -> list[dict]:
        candidates = []
        current_time = datetime.now(timezone.utc)
        
        # Filter: only active and un-superseded memories
        active_memories = [
            m for m in self.memories 
            if not m.is_deleted and not m.superseded_at and not m.valid_to
        ]

        for m in active_memories:
            m.calculate_decay(current_time)
            semantic_score = get_cosine_similarity(query, m.content)
            # Recompute total score using retrieval weights (0.6 semantic + 0.4 decay)
            relevance = (0.6 * semantic_score) + (0.4 * m.decay_score)
            
            candidates.append({
                "memory": m,
                "semantic_score": semantic_score,
                "decay_score": m.decay_score,
                "relevance": relevance
            })

        # Sort and touch the top-K accessed memories
        candidates.sort(key=lambda x: x["relevance"], reverse=True)
        results = candidates[:top_k]
        
        for res in results:
            res["memory"].access()
            
        return results

# ── CLI Interactive Loop ─────────────────────────────────────────────────────
def main():
    sys = SandboxMemorySystem()
    print(f"\n{BOLD}{GREEN}🧠 Bitemporal Memory Sandbox active!{RESET}")
    print("Experience real-time guardrails, decay math, and contradiction resolution.")
    
    while True:
        print(f"\n{BOLD}Choose an Action:{RESET}")
        print("1. 📝 Write a New Memory")
        print("2. 🔍 Search Memories (Hybrid Retrieval & Decay)")
        print("3. ⚡ Trigger a Contradiction Guardrail")
        print("4. ⏳ View Bitemporal History Graph")
        print("5. 📜 View System Prompt Context")
        print("6. 🚪 Exit")
        
        choice = input(f"{BOLD}\nEnter choice (1-6): {RESET}").strip()
        
        if choice == "1":
            print_header("Write a New Memory")
            content = input("Enter memory content: ").strip()
            if not content:
                continue
            
            mtype = input("Type (episodic/semantic/procedural) [default: semantic]: ").strip() or "semantic"
            try:
                importance = float(input("Importance (0.0 to 1.0) [default: 0.5]: ").strip() or "0.5")
            except ValueError:
                importance = 0.5
            
            tags_in = input("Comma-separated tags: ").strip()
            tags = [t.strip() for t in tags_in.split(",")] if tags_in else []
            
            status, res = sys.write_memory(content, mtype, importance, tags, "user_explicit")
            
            if status == "SUCCESS" and isinstance(res, MockMemory):
                print(f"\n{GREEN}✅ Memory Recorded Successfully!{RESET}")
                print(f"ID: {res.id}")
                print(f"Initial Decay Score: {res.decay_score:.3f}")
            elif status == "DUPLICATE":
                print(f"\n{YELLOW}⚠️  Duplicate Rejected! An identical active memory exists.{RESET}")
            elif status == "CONTRADICTION" and isinstance(res, tuple):
                existing, sim = res
                print(f"\n{RED}❌ Guardrail Stopped Write: Contradiction Detected!{RESET}")
                print(f"New entry conflicts with existing memory (Similarity: {sim:.2%})")
                print(f"Existing: '{existing.content}'")

        elif choice == "2":
            print_header("Hybrid Retrieval & Decay")
            query = input("Enter search query: ").strip()
            if not query:
                continue
                
            results = sys.retrieve_memories(query)
            
            print(f"\n{BOLD}{'Memory Content':<55} | {'Semantic':<8} | {'Decay':<6} | {'Relevance':<8}{RESET}")
            print("-" * 90)
            for r in results:
                mem = r["memory"]
                stale_flag = f" {YELLOW}[STALE]{RESET}" if mem.decay_score < 0.3 else ""
                print(f"{mem.content[:55]:<55} | {r['semantic_score']:8.3f} | {r['decay_score']:6.3f} | {r['relevance']:8.3f}{stale_flag}")

        elif choice == "3":
            print_header("Triggering Contradiction Rule")
            print("Let's add conflicting memory. Currently, we have:")
            print(f" {CYAN}* 'User prefers using VS Code with vim keybindings'{RESET}")
            print("\nEntering a contradiction like: 'User dislikes using VS Code and prefers Emacs'")
            
            content = input("\nEnter contradicting text: ").strip()
            status, res = sys.write_memory(content, "semantic", 0.9, ["editor"], "user_explicit")
            
            if status == "CONTRADICTION" and isinstance(res, tuple):
                existing, sim = res
                print(f"\n{RED}🚨 [Guardrail Lock] Contradiction detected! (Cosine Similarity: {sim:.2%}){RESET}")
                print(f"New Content:   '{content}'")
                print(f"Existing Fact: '{existing.content}'")
                
                print(f"\n{BOLD}How do you want to resolve this?{RESET}")
                print("1. Supersede (Set old as superseded, insert new as the active version)")
                print("2. Keep both as parallel realities")
                print("3. Cancel")
                
                res_choice = input("\nEnter choice (1-3): ").strip()
                if res_choice == "1":
                    sys.resolve_contradiction(existing.id, content, "supersede")
                    print(f"\n{GREEN}✅ Resolved! Historic version superseded and new memory written.{RESET}")
                elif res_choice == "2":
                    sys.resolve_contradiction(existing.id, content, "keep_both")
                    print(f"\n{GREEN}✅ Resolved! Both memories are stored independently.{RESET}")
                else:
                    print("\nCancelled contradiction resolution.")
            else:
                print(f"\n{YELLOW}No direct contradiction detected. Memory added or rejected as duplicate.{RESET}")

        elif choice == "4":
            print_header("Bitemporal Snapshot Graph")
            print("Current Database State (including superseded versions):\n")
            for m in sys.memories:
                status_str = f"{GREEN}[ACTIVE]{RESET}"
                if m.is_deleted:
                    status_str = f"{RED}[DELETED]{RESET}"
                elif m.superseded_at:
                    status_str = f"{YELLOW}[SUPERSEDED]{RESET}"
                
                print(f"📄 Content: '{m.content}'")
                print(f"   Status:  {status_str}")
                print(f"   System:  Created: {m.created_at.strftime('%X')} | Superseded: {m.superseded_at.strftime('%X') if m.superseded_at else 'None'}")
                print(f"   Reality: Valid From: {m.valid_from.strftime('%X')} | Valid To: {m.valid_to.strftime('%X') if m.valid_to else 'Forever'}")
                if m.supersedes_id:
                    print(f"   Lineage: 🔗 Supersedes Memory ID {str(m.supersedes_id)[:8]}")
                print()

        elif choice == "5":
            print_header("System Prompt Integration Block")
            print("Below is the context block injected into the LLM system prompt:")
            print(f"\n{BOLD}========================================================================{RESET}")
            print(f"## User Memory Context")
            print(f"[Retrieved: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} | Active Memories]")
            print(f"========================================================================{RESET}")
            
            active = [m for m in sys.memories if not m.is_deleted and not m.superseded_at]
            for idx, m in enumerate(active, 1):
                stale_tag = " (⚠ flagged stale)" if m.decay_score < 0.3 else ""
                print(f"{idx}. [{m.memory_type}|importance:{m.importance:.1f}|decay:{m.decay_score:.2f}] {m.content}{stale_tag}")
            print(f"{BOLD}========================================================================{RESET}")

        elif choice == "6":
            print(f"\n{BOLD}Goodbye! Keep building awesome systems.{RESET}\n")
            break

if __name__ == "__main__":
    main()
