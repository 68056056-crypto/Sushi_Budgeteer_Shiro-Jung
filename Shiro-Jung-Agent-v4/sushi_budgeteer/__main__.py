"""Terminal client for the same Agent and MCP loop used by Streamlit."""
from .agent import BudgeteerAgent
from .policy import DISCLAIMER

def main():
    print(DISCLAIMER)
    agent=BudgeteerAgent()
    print('Shiro-Jung: บอกงบและจำนวนคนได้เลย /reset เริ่มใหม่ /exit จบ')
    while True:
        text=input('คุณ: ').strip()
        if text=='/exit': break
        if text=='/reset':
            agent.state.reset();print('รีเซ็ตบทสนทนาแล้ว');continue
        if text: print('Shiro-Jung:',agent.chat(text))

if __name__=='__main__': main()
