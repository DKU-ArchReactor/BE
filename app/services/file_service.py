import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.project import Project
from app.models.user import User
from app.schemas.file import FileCreate

DEFAULT_PROJECT_TITLE = "Default Project"


class FileNotFoundError(Exception):
    pass


class FileAccessDeniedError(Exception):
    pass


def get_or_create_default_project(db: Session, user: User) -> Project:
    project = db.scalar(
        select(Project)
        .where(Project.user_id == user.user_id)
        .order_by(Project.last_modified.asc())
        .limit(1)
    )
    if project is not None:
        return project

    project = Project(user_id=user.user_id, title=DEFAULT_PROJECT_TITLE)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_files(db: Session, user: User) -> list[File]:
    return list(
        db.scalars(
            select(File)
            .join(Project, File.project_id == Project.project_id)
            .where(Project.user_id == user.user_id)
            .order_by(File.updated_at.desc())
        ).all()
    )


def get_file(db: Session, file_id: uuid.UUID, user: User) -> File:
    file = db.get(File, file_id)
    if file is None:
        raise FileNotFoundError()
    if file.project.user_id != user.user_id:
        raise FileAccessDeniedError()
    return file


def upsert_file(db: Session, user: User, data: FileCreate) -> File:
    project = get_or_create_default_project(db, user)

    existing = db.scalar(
        select(File).where(
            File.project_id == project.project_id,
            File.title == data.title,
        )
    )
    if existing is not None:
        existing.content = data.content
        existing.lang = data.lang
        db.commit()
        db.refresh(existing)
        return existing

    file = File(
        project_id=project.project_id,
        title=data.title,
        content=data.content,
        lang=data.lang,
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


def delete_file(db: Session, file_id: uuid.UUID, user: User) -> None:
    file = get_file(db, file_id, user)
    db.delete(file)
    db.commit()
