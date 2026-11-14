"""Portable experience-card Skill optimization, based on current research code."""
from .contracts import Task, Execution, Score, Experience, HarnessAdapter, Judge, ReflectionModel
from .core import LearningConfig, learn, render_bank, select_candidate
from .pipeline import SkillOptimizer

__version__ = '1.0.0'
