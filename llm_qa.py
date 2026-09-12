"""รับคำถามจากผู้ใช้ทาง terminal แล้วให้ LLM (OpenAI) ตอบ พิมพ์ 'exit' เพื่อออก"""

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def ask_llm(question: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
    )
    return response.choices[0].message.content


def main() -> None:
    print(f"ถามอะไรก็ได้ (โมเดล: {MODEL}) — พิมพ์ 'exit' เพื่อออก")
    while True:
        question = input("\nคำถาม: ").strip()
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue
        answer = ask_llm(question)
        print(f"\nคำตอบ: {answer}")


if __name__ == "__main__":
    main()
