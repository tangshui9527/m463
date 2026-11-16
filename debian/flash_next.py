import subprocess

cmd = 'cd ~/mtkclient && echo 1122 | sudo -S python3 -u mtk.py multi "w lk lk-stock.img;reset"'
print("Target cmd:", cmd)
