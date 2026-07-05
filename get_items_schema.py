import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://postgres:dKpaHEDsCTQK1FUp77wVPI_rfb4nf5nQfcsoXykUEfE@database.debuggers.co.in:5432/OrderServiceDb")
    
    rows = await conn.fetch("SELECT column_name, data_type, column_default, is_nullable FROM information_schema.columns WHERE table_name = 'orders_items';")
    for row in rows:
        print(dict(row))

    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
