# app/db/model.py
from datetime import datetime
from sqlalchemy import text
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from config import SYSTEM_USER_ID, BASE_CHARACTERISTICS

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sets = relationship("Set", back_populates="user")


class Set(Base):
    __tablename__ = "sets"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), index=True)
    description = Column(String(255))
    banks = Column(String(500))

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="sets")

    created_at = Column(DateTime, default=datetime.utcnow)


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
    set_id = Column(Integer, ForeignKey("sets.id"))
    bank_id = Column(Integer, ForeignKey("banks.id"))
    name = Column(String(100))
    url = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

    set = relationship("Set")


class Characteristic(Base):
    __tablename__ = "characteristics"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    set_id = Column(Integer, ForeignKey("sets.id"), nullable=True)

    name = Column(String(100), index=True, nullable=False)
    description = Column(Text)
    value_hint = Column(Text)

    user = relationship("User")
    set = relationship("Set")


class Data(Base):
    __tablename__ = "data"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product_id = Column(Integer, nullable=True)
    characteristics = Column(Text, nullable=True)  # устарело
    characteristic_id = Column(Integer, nullable=True)
    card_set = Column(String(255))
    payload = Column(JSON)  # сырые данные
    value = Column(Text, nullable=False, default="")  



class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    action = Column(String(50))  
    status = Column(String(50)) 
    message = Column(Text)
    tokens_used = Column(Integer, default=0) 


engine = create_engine("sqlite:///cards.db", echo=False, future=True)
Base.metadata.create_all(bind=engine) 
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_sets_for_user(db, user_id: int | None):
    if user_id is None:
        return db.query(Set).filter(Set.user_id == SYSTEM_USER_ID).all()

    return db.query(Set).filter(
        (Set.user_id == SYSTEM_USER_ID) | (Set.user_id == user_id)
    ).all()



def migrate_products():
    db = SessionLocal()
    
    # Получаем банки по ID для правильных ссылок
    banks_map = {b.name: b.id for b in db.query(Bank).all()}
    
    # Продукты для каждого набора
    products_data = {
        "Стандарт": [
            ("Сбер", "SberCard", "https://www.sber-bank.by/card/sbercard"),
            ("Альфа Банк", "Alfa Classic", "https://www.alfabank.by/besmart/alfa-platinum/"),
            ("Беларусбанк", "Щедрая Mastercard", "https://belarusbank.by/fizicheskim_licam/cards/shchodraya-mastercard/"),
            ("МТБанк", "Cactus", "https://www.mtbank.by/cards/cactus/tarifs/"),
            ("Приорбанк", "Яркая карта", "https://www.priorbank.by/offers/cards/yarkaya-karta"),
            ("БНБ", "1-2-3", "https://bnb.by/o-lichnom/bankovskie-kartochki/1-2-3/"),
            ("ВТБ", "VTB Card", "https://www.vtb.by/more#vtb_tab-condition"),
            ("Белгазпромбанк", "Classic Card", "https://belgazprombank.by/personal_banking/plastikovie_karti/raschetnie_karti/classic-card/cashalot/"),
            ("Белагропромбанк", "Пакет Лайт", "https://www.belapb.by/chastnomu-klientu/bankovskie-karty/paket-layt/paket-layt/"),
            ("БелВэб", "Simple", "https://www.belveb.by/package/simple/"),
            ("Дабрабыт", "Спраyная", "https://bankdabrabyt.by/personal/cards/paket-uslug-spra-naya/?nocache=1769017617302"),
        ],
        "Премиум": [
            ("Сбер", "СберКарта Ультра 2.0", "https://www.sber-bank.by/card/sbercard"),
            ("Альфа Банк", "Alfa Platinum", "https://www.alfabank.by/besmart/alfa-classic/"),
            ("Беларусбанк", "Platinum", "https://belarusbank.by/fizicheskim_licam/cards/platinum-unionpay/"),
            ("МТБанк", "Prime-line", "https://www.mtbank.by/prime/prime-line/"),
            ("Приорбанк", "Visa Signature", "https://www.priorbank.by/offers/cards/visa-signature"),
            ("БНБ", "Masterсard World Elite", "https://bnb.by/o-lichnom/bankovskie-kartochki/mastercard-world-elite/"),
            ("ВТБ", "Infinite", "https://www.vtb.by/chastnym-licam/bankovskie-kartochki/debetovye-kartochki/premialnaya-kartochka-infinite"),
            ("Белгазпромбанк", "Visa Platinum", "https://belgazprombank.by/personal_banking/plastikovie_karti/raschetnie_karti/premial_nie_karti/premial_naja_karta_visa_platin/"),
            ("Белагропромбанк", "Mastercard World Black Edition", "https://www.belapb.by/chastnomu-klientu/bankovskie-karty/mastercard/mastercard-world-black-edition/"),
            ("БелВэб", "Всё по максимуму", "https://www.belveb.by/package/maximum/"),
            ("Дабрабыт", "Разам. Для унікальнага", "https://bankdabrabyt.by/personal/razam/razam-dlya-unikalnaga/"),
        ]
    }
    
    added = 0
    for set_name, prods in products_data.items():
        set_obj = db.query(Set).filter_by(name=set_name).first()
        if not set_obj:
            print(f"Набор '{set_name}' не найден в БД")
            continue
            
        for bank_name, prod_name, prod_url in prods:
            bank_id = banks_map.get(bank_name)
            if not bank_id:
                print(f"Банк '{bank_name}' не найден в БД")
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
                print(f"Продукт уже существует: {set_name} -> {bank_name}: {prod_name}")
    
    db.commit()
    print(f"\n✅ Всего добавлено {added} продуктов")
    db.close()




def init_db():
    Base.metadata.create_all(bind=engine)

def migrate_banks():
    db = SessionLocal()

    # 1. Проверить/создать пользователь для наборов
    user = db.query(User).filter(User.tg_id == 1).first()
    if not user:
        user = User(tg_id=1)
        db.add(user)
        db.commit()

    # 2. Заполнить таблицу banks, если она пустая
    banks_data = [
        ("Сбер", "https://www.sber-bank.by/card/sbercard", "gigachat"),
        ("Альфа Банк", "https://www.alfabank.by/besmart/alfa-classic/", "gigachat"),
        ("Беларусбанк", "https://belarusbank.by/fizicheskim_licam/cards/shchodraya-mastercard/", "gigachat"),
        ("МТБанк", "https://www.mtbank.by/cards/cactus/tarifs/", "gigachat"),
        ("Приорбанк", "https://www.priorbank.by/offers/cards/yarkaya-karta", "gigachat"),
        ("БНБ", "https://bnb.by/o-lichnom/bankovskie-kartochki/1-2-3/", "gigachat"),
        ("ВТБ", "https://www.vtb.by/more#vtb_tab-condition", "gigachat"),
        ("Белгазпромбанк", "https://belgazprombank.by/personal_banking/plastikovie_karti/raschetnie_karti/classic-card/cashalot/", "gigachat"),
        ("Белагропромбанк", "https://www.belapb.by/chastnomu-klientu/bankovskie-karty/paket-layt/paket-layt/", "gigachat"),
        ("БелВэб", "https://www.belveb.by/package/simple/", "gigachat"),
        ("Дабрабыт", "https://bankdabrabyt.by/personal/cards/paket-uslug-spra-naya/?nocache=1769017617302", "gigachat"),
    ]

    existing_names = {b.name for b in db.query(Bank).all()}
    for name, url, parser_type in banks_data:
        if name not in existing_names:
            bank = Bank(name=name, url=url, parser_type=parser_type)
            db.add(bank)
            print(f" Добавлен банк: {name}")

    db.commit()
    print(" Банки внесены в базу.")

    # 3. Теперь уже можем создать наборы
    all_banks = [b.name for b in db.query(Bank).all()]
    sets_data = [
        ("Стандарт", "Все банки (базовый набор)", ",".join(all_banks)),
        ("Премиум", "Все банки (премиум набор)", ",".join(all_banks)),
    ]

    added_sets = 0
    for name, description, banks_str in sets_data:
        existing = db.query(Set).filter(Set.name == name, Set.user_id == user.id).first()
        if not existing:
            set_obj = Set(
                name=name,
                description=description,
                banks=banks_str,
                user_id=user.id,
            )
            db.add(set_obj)
            added_sets += 1
            print(f" Добавлен набор: {name}")

    db.commit()
    print(f"Добавлено {added_sets} наборов")
    db.close()


def recreate_data_table():
    from sqlalchemy import text
    
    db = SessionLocal()
    try:
        # 1. Сохраняем данные (если есть)
        print("Сохраняем существующие данные...")
        existing_data = db.execute(text("""
            SELECT user_id, created_at, product_id, characteristic_id, card_set, 
                   COALESCE(value, characteristics) as value, payload
            FROM data
        """)).fetchall()
        
        # 2. Удаляем старую таблицу
        db.execute(text("DROP TABLE IF EXISTS data"))
        db.commit()
        print("Старая таблица data удалена")
        
        # 3. Пересоздаём модели
        Base.metadata.create_all(bind=engine)
        print("Новая таблица data создана")
        
        # 4. Восстанавливаем данные
        if existing_data:
            for row in existing_data:
                data_record = Data(
                    user_id=row[0],
                    product_id=row[2],
                    characteristic_id=row[3],
                    card_set=row[4],
                    value=row[5] or "",
                    payload=row[6] or {}
                )
                db.add(data_record)
            db.commit()
            print(f"Восстановлено {len(existing_data)} записей")
        else:
            print("Нет данных для восстановления")
            
    except Exception as e:
        print(f"Ошибка пересоздания: {e}")
        db.rollback()
    finally:
        db.close()
        print("ГОТОВО! Теперь парсинг будет работать")


def migrate_base_characteristics():
    db = SessionLocal()
    try:
        sys_user = db.query(User).filter(User.tg_id == 1).first()
        if not sys_user:
            sys_user = User(tg_id=1)
            db.add(sys_user)
            db.commit()
            db.refresh(sys_user)

        # Глобальные характеристики (set_id=None)
        existing_global = {c.name for c in db.query(Characteristic)
                          .filter(Characteristic.user_id == sys_user.id, Characteristic.set_id.is_(None)).all()}
        
        for name, desc, hint in BASE_CHARACTERISTICS:
            if name not in existing_global:
                char = Characteristic(
                    user_id=sys_user.id,
                    set_id=None,
                    name=name,
                    description=desc,
                    value_hint=hint
                )
                db.add(char)
        
        db.commit()

        # Копируем в наборы пользователя
        user_sets = db.query(Set).filter(Set.user_id == sys_user.id).all()
        for set_obj in user_sets:
            existing_set = {c.name for c in db.query(Characteristic)
                           .filter(Characteristic.set_id == set_obj.id).all()}
            for name, desc, hint in BASE_CHARACTERISTICS:
                if name not in existing_set:
                    char = Characteristic(
                        user_id=sys_user.id,
                        set_id=set_obj.id,
                        name=name,
                        description=desc,
                        value_hint=hint
                    )
                    db.add(char)
        
        db.commit()
        print(f"✅ Добавлены характеристики в {len(user_sets)} наборов")
    finally:
        db.close()


def migrate_logs_add_tokens_column():
    
    db = SessionLocal()
    
    try:
        result = db.execute(text("PRAGMA table_info(logs)"))
        columns = [row[1] for row in result.fetchall()]
        
        if "tokens_used" not in columns:
            print("Добавляю колонку tokens_used в таблицу logs...")
            
            db.execute(text("ALTER TABLE logs ADD COLUMN tokens_used INTEGER DEFAULT 0"))
            db.commit()
            
            print("✅ Колонка tokens_used успешно добавлена!")
            return True
        else:
            print("✅ Колонка tokens_used уже существует")
            return False
            
    except Exception as e:
        print(f"Ошибка миграции: {e}")
        db.rollback()
        return False
    finally:
        db.close()