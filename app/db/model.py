from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, JSON, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Data(Base):
    __tablename__ = "data"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    characteristics = Column(Text)
    card_set = Column(String(255))
    payload = Column(JSON)

class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    action = Column(String(50))
    status = Column(String(50))
    message = Column(Text, nullable=True)

class Bank(Base):
    __tablename__ = "banks"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, index=True)
    url = Column(String(500))
    parser_type = Column(String(50), default="gigachat")
    created_at = Column(DateTime, default=datetime.utcnow)

engine = create_engine("sqlite:///cards.db", echo=False, future=True)
Base.metadata.create_all(bind=engine) 
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    Base.metadata.create_all(bind=engine)

def migrate_banks():
    db = SessionLocal()
    banks_data = [
        ("Сбер", "https://www.sber-bank.by/card/sbercard"),
        ("Альфа Банк", "https://www.alfabank.by/besmart/alfa-classic/"),
        ("Беларусбанк", "https://belarusbank.by/fizicheskim_licam/cards/shchodraya-mastercard/"),
        ("МТБанк", "https://www.mtbank.by/cards/cactus/tarifs/"),
        ("Приорбанк", "https://www.priorbank.by/offers/cards/yarkaya-karta"),
        ("БНБ", "https://bnb.by/o-lichnom/bankovskie-kartochki/1-2-3/"),
        ("ВТБ", "https://www.vtb.by/more#vtb_tab-condition"),
        ("Белгазпромбанк", "https://belgazprombank.by/personal_banking/plastikovie_karti/raschetnie_karti/classic-card/cashalot/"),
        ("Белагропромбанк", "https://www.belapb.by/chastnomu-klientu/bankovskie-karty/paket-layt/paket-layt/"),
        ("БелВэб", "https://www.belveb.by/package/simple/"),
        ("Дабрабыт", "https://bankdabrabyt.by/personal/cards/paket-uslug-spra-naya/?nocache=1769017617302"),
    ]
    
    added = 0
    for name, url in banks_data:
        if not db.query(Bank).filter_by(name=name).first():
            bank = Bank(name=name, url=url)
            db.add(bank)
            added += 1
    db.commit()
    print(f"добавлено {added} банков")
    db.close()
