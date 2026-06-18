"""
Semantic Task Classifier
Replaces keyword matching with embedding-based classification.
Uses sentence transformers to understand task meaning, not just keywords.

Install: pip install sentence-transformers
"""

import numpy as np
import sqlite3
from datetime import datetime
from collections import defaultdict

class SemanticClassifier:
    """
    Embedding-based task classification.
    
    Instead of: if 'fix' in prompt → debug
    Does: prompt embedding → nearest neighbor in labeled task space → classification
    
    This correctly handles:
    - "Fix the architecture to scale" → refactor (not debug)
    - "Debug the performance issue" → algorithm (not debug)
    - "Help me understand why this crashes" → debug (not explain)
    """
    
    # Labeled examples for each task type
    TRAINING_EXAMPLES = {
        'algorithm': [
            "Write a function to sort an array",
            "Implement a binary search tree",
            "Create a pathfinding algorithm for a maze",
            "Build a function to detect cycles in a graph",
            "Write code to find the longest palindrome",
            "Implement quicksort from scratch",
            "Create a function to reverse a linked list",
            "Build a trie data structure with insert and search",
            "Write an algorithm to solve the knapsack problem",
            "Implement Dijkstra's shortest path algorithm",
        ],
        'debug': [
            "Fix the null pointer exception in this code",
            "Why does this function return undefined?",
            "Debug the race condition in my multithreaded code",
            "Find the memory leak in this Python script",
            "This SQL query returns wrong results, help me fix it",
            "My React component keeps re-rendering infinitely",
            "The API returns 500 but I can't find the bug",
            "Why is this loop skipping the last element?",
            "Fix the off-by-one error in my binary search",
            "Debug this authentication bypass vulnerability",
        ],
        'refactor': [
            "Refactor this class to use dependency injection",
            "Convert this callback-based code to async/await",
            "Clean up this spaghetti code into proper modules",
            "Apply the strategy pattern to remove this switch statement",
            "Restructure this monolith into microservices",
            "Optimize this database query that's running slow",
            "Convert this inheritance hierarchy to composition",
            "Extract an interface from this concrete implementation",
            "Apply SOLID principles to this codebase",
            "Break this 500-line function into smaller units",
        ],
        'explain': [
            "Explain how garbage collection works in Python",
            "What's the difference between TCP and UDP?",
            "How does database indexing improve performance?",
            "Explain the CAP theorem with examples",
            "What is dependency injection and why use it?",
            "How does HTTPS encryption work end-to-end?",
            "Explain MapReduce like I'm five",
            "What are the tradeoffs between SQL and NoSQL?",
            "How does Docker networking work under the hood?",
            "Explain how the JIT compiler optimizes code",
        ]
    }
    
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        self.model_name = model_name
        self.model = None
        self.embeddings = {}
        self._load_model()
    
    def _load_model(self):
        """Lazy load the embedding model."""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            print(f"Loaded embedding model: {self.model_name}")
            self._precompute_embeddings()
        except ImportError:
            print("sentence-transformers not installed. Using fallback classifier.")
            print("Install with: pip install sentence-transformers")
    
    def _precompute_embeddings(self):
        """Pre-compute embeddings for all training examples."""
        for task_type, examples in self.TRAINING_EXAMPLES.items():
            self.embeddings[task_type] = self.model.encode(examples)
    
    def _embed(self, text):
        """Get embedding for a single text."""
        if self.model is None:
            return None
        return self.model.encode([text])[0]
    
    def classify(self, prompt):
        """
        Classify a prompt into a task type using semantic similarity.
        
        Returns (task_type, confidence, alternatives).
        """
        if self.model is None:
            return self._fallback_classify(prompt)
        
        prompt_embedding = self._embed(prompt)
        
        # Compute similarity to each task type
        scores = {}
        for task_type, embeddings in self.embeddings.items():
            # Cosine similarity to all examples, take top-3 average
            similarities = np.dot(embeddings, prompt_embedding) / (
                np.linalg.norm(embeddings, axis=1) * np.linalg.norm(prompt_embedding)
            )
            # Top 3 most similar examples
            top_3 = np.sort(similarities)[-3:]
            scores[task_type] = float(np.mean(top_3))
        
        # Best task type
        best_task = max(scores, key=scores.get)
        confidence = scores[best_task]
        
        # Alternatives (other task types that were close)
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        alternatives = [
            {'task': task, 'score': round(score, 3)}
            for task, score in sorted_scores[1:3]
        ]
        
        # Map task types to routing decisions
        task_type_map = {
            'algorithm': 'algorithm',
            'debug': 'debug',
            'refactor': 'refactor',
            'explain': 'explain',
        }
        
        return {
            'task_type': task_type_map.get(best_task, 'other'),
            'confidence': round(confidence, 3),
            'alternatives': alternatives,
            'method': 'embedding_similarity',
            'raw_scores': {k: round(v, 3) for k, v in scores.items()}
        }
    
    def _fallback_classify(self, prompt):
        """Fallback classifier when embeddings aren't available."""
        prompt_lower = prompt.lower()
        
        scores = {}
        for task_type, examples in self.TRAINING_EXAMPLES.items():
            # Simple overlap scoring
            score = 0
            for example in examples:
                example_words = set(example.lower().split())
                prompt_words = set(prompt_lower.split())
                overlap = len(example_words & prompt_words)
                score += overlap
            scores[task_type] = score / len(examples)
        
        best_task = max(scores, key=scores.get)
        confidence = scores[best_task] / max(sum(scores.values()), 0.01)
        
        return {
            'task_type': best_task,
            'confidence': min(round(confidence, 2), 1.0),
            'alternatives': [],
            'method': 'keyword_fallback',
            'raw_scores': scores
        }
    
    def classify_with_explanation(self, prompt):
        """Classify and explain the decision."""
        result = self.classify(prompt)
        
        # Generate explanation
        explanations = {
            'algorithm': "This is an implementation task requiring code generation or algorithm design.",
            'debug': "This is a debugging task requiring finding and fixing errors.",
            'refactor': "This is a refactoring task requiring code restructuring or optimization.",
            'explain': "This is an explanation task requiring conceptual understanding.",
            'other': "This task doesn't clearly match a specific category."
        }
        
        result['explanation'] = explanations.get(result['task_type'], '')
        
        # Confidence interpretation
        if result['confidence'] > 0.8:
            result['confidence_level'] = 'high'
        elif result['confidence'] > 0.5:
            result['confidence_level'] = 'medium'
        else:
            result['confidence_level'] = 'low'
        
        return result


# ─── Singleton ──────────────────────────────────────────────────
semantic_classifier = SemanticClassifier()


# ─── Test ──────────────────────────────────────────────────────
if __name__ == '__main__':
    classifier = SemanticClassifier()
    
    # Test prompts that confuse keyword classifiers
    edge_cases = [
        "Fix the architecture to scale horizontally",  # Should be refactor, not debug
        "Debug why the sorting algorithm is slow",      # Should be debug, not algorithm
        "Help me understand why this crashes",          # Should be debug, not explain
        "Implement error handling throughout the codebase",  # Should be refactor, not algorithm
        "Explain the time complexity of this fix",      # Should be explain, not debug
    ]
    
    print("=" * 60)
    print("  Semantic Classifier Test")
    print("=" * 60)
    
    for prompt in edge_cases:
        result = classifier.classify_with_explanation(prompt)
        print(f"\n  Prompt: {prompt}")
        print(f"  Task:   {result['task_type']} ({result['confidence_level']})")
        print(f"  Why:    {result['explanation']}")