from main import connect


def create(con):
    print("=== CREATE ===")
    con.execute("""
        CREATE TABLE IF NOT EXISTS my_lake.main.products (
            id     INT,
            name   VARCHAR,
            price  DOUBLE,
            stock  INT
        )
    """)
    con.execute("""
        INSERT INTO my_lake.main.products VALUES
            (1, 'Laptop',   9999.0, 15),
            (2, 'Mouse',     299.0, 50),
            (3, 'Keyboard', 1299.0, 30)
    """)
    print("3 rows inserted into my_lake.main.products")
    print(con.execute("SELECT * FROM my_lake.main.products").fetchdf())


def read(con):
    print("\n=== READ ===")
    print(con.execute("SELECT * FROM my_lake.main.products").fetchdf())


def update(con):
    print("\n=== UPDATE ===")
    con.execute("""
        UPDATE my_lake.main.products
        SET price = 8999.0
        WHERE id = 1
    """)
    print("Updated price of id=1 to 8999.0")
    print(con.execute("SELECT * FROM my_lake.main.products").fetchdf())


def delete(con):
    print("\n=== DELETE ===")
    con.execute("""
        DELETE FROM my_lake.main.products
        WHERE id = 2
    """)
    print("Deleted row with id=2")
    print(con.execute("SELECT * FROM my_lake.main.products").fetchdf())


def main():
    con = connect()
    create(con)
    read(con)
    update(con)
    delete(con)


if __name__ == "__main__":
    main()
