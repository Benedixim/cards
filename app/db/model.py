from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, Text, JSON, create_engine,
    ForeignKey  
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


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    set_id = Column(Integer, ForeignKey("sets.id"))  # Ссылка на набор!
    bank_id = Column(Integer, ForeignKey("banks.id"))
    name = Column(String(100))  # "SberCard", "Alfa Classic"
    url = Column(String(500))   # Может отличаться от bank.url
    created_at = Column(DateTime, default=datetime.utcnow)

class Characteristic(Base):
    __tablename__ = "characteristics"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)  # "type", "currency", "validity"
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

class Set(Base):
    __tablename__ = "sets"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, index=True)  # "Стандарт", "Премиум"
    description = Column(String(255))  # "Базовые карты", "Премиум карты"
    banks = Column(String(500))  # "Сбер,Беларусбанк,МТБанк"
    created_at = Column(DateTime, default=datetime.utcnow)

def migrate_products():
    db = SessionLocal()
    
    # Получаем банки по ID для правильных ссылок
    banks_map = {b.name: b.id for b in db.query(Bank).all()}
    
    # Продукты для каждого набора
    products_data = {
        "Стандарт": [
            ("Сбер", "SberCard", "https://www.sber-bank.by/card/sbercard"),
            ("Альфа Банк", "Alfa Classic", "https://www.alfabank.by/besmart/alfa-classic/"),
            ("Беларусбанк", "Щедрая Mastercard", "https://belarusbank.by/fizicheskim_licam/cards/shchodraya-mastercard/"),
            ("МТБанк", "Cactus", "https://www.mtbank.by/cards/cactus/tarifs/"),
            ("Приорбанк", "Яркая карта", "https://www.priorbank.by/offers/cards/yarkaya-karta"),
            ("БНБ", "1-2-3", "https://bnb.by/o-lichnom/bankovskie-kartochki/1-2-3/"),
            ("ВТБ", "VTB Card", "https://www.vtb.by/more#vtb_tab-condition"),
            ("Белгазпромбанк", "Classic Card", "https://belgazprombank.by/personal_banking/plastikovie_karti/raschetnie_karti/classic-card/cashalot/"),
            ("Белагропромбанк", "Пакет Лайт", "https://www.belapb.by/chastnomu-klientu/bankovskie-karty/paket-layt/paket-layt/"),
            ("БелВэб", "Simple", "https://www.belveb.by/package/simple/"),
            ("Дабрабыт", "Спра-ная", "https://bankdabrabyt.by/personal/cards/paket-uslug-spra-naya/?nocache=1769017617302"),
        ],
        "Премиум": [
            ("Сбер", "SberCard", "https://www.sber-bank.by/card/sbercard"),
            ("Альфа Банк", "Alfa Classic", "https://www.alfabank.by/besmart/alfa-classic/"),
            ("Беларусбанк", "Щедрая Mastercard", "https://belarusbank.by/fizicheskim_licam/cards/shchodraya-mastercard/"),
            ("МТБанк", "Cactus", "https://www.mtbank.by/cards/cactus/tarifs/"),
            ("Приорбанк", "Яркая карта", "https://www.priorbank.by/offers/cards/yarkaya-karta"),
        ]
    }
    
    added = 0
    for set_name, prods in products_data.items():
        set_obj = db.query(Set).filter_by(name=set_name).first()
        if not set_obj:
            print(f"❌ Набор '{set_name}' не найден в БД")
            continue
            
        for bank_name, prod_name, prod_url in prods:
            bank_id = banks_map.get(bank_name)
            if not bank_id:
                print(f"⚠️ Банк '{bank_name}' не найден в БД")
                continue
            
            # Проверяем, нет ли уже такого продукта
            existing = db.query(Product).filter_by(
                set_id=set_obj.id, 
                bank_id=bank_id, 
                name=prod_name
            ).first()
            
            if not existing:
                product = Product(
                    set_id=set_obj.id,
                    bank_id=bank_id,
                    name=prod_name,
                    url=prod_url
                )
                db.add(product)
                added += 1
                print(f"✅ Добавлен продукт: {set_name} -> {bank_name}: {prod_name}")
            else:
                print(f"⏭️ Продукт уже существует: {set_name} -> {bank_name}: {prod_name}")
    
    db.commit()
    print(f"\n✅ Всего добавлено {added} продуктов")
    db.close()

engine = create_engine("sqlite:///cards.db", echo=False, future=True)
Base.metadata.create_all(bind=engine) 
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    Base.metadata.create_all(bind=engine)

def migrate_banks():
    db = SessionLocal()
    # Получаем ВСЕ банки из таблицы banks
    all_banks = [b.name for b in db.query(Bank).all()]
    
    sets_data = [
        ("Стандарт", "Все банки (базовый набор)", ",".join(all_banks)),
        ("Премиум", "Все банки (премиум набор)", ",".join(all_banks)),
    ]
    
    added = 0
    for name, description, banks in sets_data:
        if not db.query(Set).filter_by(name=name).first():
            set_obj = Set(name=name, description=description, banks=banks)
            db.add(set_obj)
            added += 1
    
    db.commit()
    print(f"✅ Добавлено {added} наборов (всего банков: {len(all_banks)})")
    db.close()
