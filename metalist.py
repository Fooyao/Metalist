import base64
import os
import random
import string
import sys
import asyncio
from multiprocessing import Pool
import cv2
import numpy as np
import httpx
from eth_account.messages import encode_defunct
from loguru import logger
from web3 import AsyncWeb3

logger.remove()
logger.add(sys.stdout, colorize=True, format="<g>{time:HH:mm:ss:SSS}</g> | <c>{level}</c> | <level>{message}</level>")


class GapLocator:

    def __init__(self, gap, bg):
        """
        init code
        :param gap: 缺口图片
        :param bg: 背景图片
        """
        self.gap = gap
        self.bg = bg

    @staticmethod
    def clear_white(img):
        """
        清除图片的空白区域，这里主要清除滑块的空白
        :param img:
        :return:
        """
        img = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
        rows, cols, channel = img.shape
        min_x = 255
        min_y = 255
        max_x = 0
        max_y = 0
        for x in range(1, rows):
            for y in range(1, cols):
                t = set(img[x, y])
                if len(t) >= 2:
                    if x <= min_x:
                        min_x = x
                    elif x >= max_x:
                        max_x = x

                    if y <= min_y:
                        min_y = y
                    elif y >= max_y:
                        max_y = y
        img1 = img[min_x: max_x, min_y: max_y]
        return img1

    @staticmethod
    def template_match(tpl, target):
        """
        背景匹配
        :param tpl:
        :param target:
        :return:
        """
        th, tw = tpl.shape[:2]
        result = cv2.matchTemplate(target, tpl, cv2.TM_CCOEFF_NORMED)
        # 寻找矩阵(一维数组当作向量,用Mat定义) 中最小值和最大值的位置
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        tl = max_loc
        br = (tl[0] + tw, tl[1] + th)
        # 绘制矩形边框，将匹配区域标注出来
        # target：目标图像
        # tl：矩形定点
        # br：矩形的宽高
        # (0, 0, 255)：矩形边框颜色
        # 1：矩形边框大小
        cv2.rectangle(target, tl, br, (0, 0, 255), 2)
        return tl

    @staticmethod
    def image_edge_detection(img):
        """
        图像边缘检测
        :param img:
        :return:
        """
        edges = cv2.Canny(img, 100, 200)
        return edges

    def run(self, is_clear_white=False):
        if is_clear_white:
            img1 = self.clear_white(self.gap)
        else:
            img1 = cv2.imdecode(np.frombuffer(self.gap, np.uint8), cv2.IMREAD_COLOR)
        img1 = cv2.cvtColor(img1, cv2.COLOR_RGB2GRAY)
        slide = self.image_edge_detection(img1)

        back = cv2.imdecode(np.frombuffer(self.bg, np.uint8), cv2.IMREAD_COLOR)
        back = self.image_edge_detection(back)

        slide_pic = cv2.cvtColor(slide, cv2.COLOR_GRAY2RGB)
        back_pic = cv2.cvtColor(back, cv2.COLOR_GRAY2RGB)
        x = self.template_match(slide_pic, back_pic)
        # 输出横坐标, 即 滑块在图片上的位置
        return x[0]


class Twitter:
    def __init__(self, auth_token, code_challenge, proxies):
        self.code_challenge, self.auth_token = code_challenge, auth_token
        bearer_token = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
        defaulf_headers = {
            "authority": "twitter.com",
            "origin": "https://twitter.com",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
            "authorization": bearer_token,
        }
        defaulf_cookies = {"auth_token": auth_token}
        self.Twitter = httpx.AsyncClient(headers=defaulf_headers, cookies=defaulf_cookies, timeout=120, proxies=proxies)
        self.auth_code = None

    async def get_auth_code(self):
        try:
            params = {
                'code_challenge': self.code_challenge,
                'code_challenge_method': 'plain',
                'client_id': 'NkxvMG1xYVBoX2J1T2pTZjBfalM6MTpjaQ',
                'redirect_uri': 'https://cardsahoy.metalist.io/airdrop-h5',
                'response_type': 'code',
                'scope': 'users.read tweet.read',
                'state': 'twitter_metalist'
            }
            response = await self.Twitter.get('https://twitter.com/i/api/2/oauth2/authorize', params=params)
            if "code" in response.json() and response.json()["code"] == 353:
                self.Twitter.headers.update({"x-csrf-token": response.cookies["ct0"]})
                return await self.get_auth_code()
            elif response.status_code == 429:
                await asyncio.sleep(5)
                return self.get_auth_code()
            elif 'auth_code' in response.json():
                self.auth_code = response.json()['auth_code']
                return True
            logger.error(f'{self.auth_token} 获取auth_code失败')
            return False
        except Exception as e:
            logger.error(e)
            return False

    async def twitter_authorize(self):
        try:
            if not await self.get_auth_code():
                return False
            data = {
                'approval': 'true',
                'code': self.auth_code,
            }
            response = await self.Twitter.post('https://twitter.com/i/api/2/oauth2/authorize', data=data)
            if 'redirect_uri' in response.text:
                return True
            elif response.status_code == 429:
                await asyncio.sleep(5)
                return self.twitter_authorize()
            logger.error(f'{self.auth_token}  推特授权失败')
            return False
        except Exception as e:
            logger.error(f'{self.auth_token}  推特授权异常：{e}')
            return False


class metalist:
    def __init__(self, private_key, auth_token, nstproxy_Channel, nstproxy_Password):
        headers = {
            'Client-App-Id': '13x67d4icclyebny'
        }
        self.private_key = private_key
        session = ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(10))
        nstproxy = f"http://{nstproxy_Channel}-residential-country_ANY-r_5m-s_{session}:{nstproxy_Password}@gw-us.nstproxy.com:24125"
        self.proxies = {'all://': nstproxy}
        self.http = httpx.AsyncClient(headers=headers, timeout=120, proxies=self.proxies)
        self.web3 = AsyncWeb3()
        self.auth_token = auth_token
        self.tokenid, self.img_id = None, None
        self.account = self.web3.eth.account.from_key(private_key)

    async def captcha(self):
        try:
            res = await self.http.post('https://game.metalist.io/api/user/genCaptcha', json={})
            if res.json()['code'] == '000000':
                block = res.json()['data']['tpImage'].replace("data:image/jpeg;base64,", "").replace("data:image/png;base64,", "")
                bg = res.json()['data']['bgImage'].replace("data:image/jpeg;base64,", "").replace("data:image/png;base64,", "")
                self.img_id = res.json()['data']['id']
                x = GapLocator(base64.b64decode(block), base64.b64decode(bg)).run()
                return await self.check(round(x * 0.496277915632754), self.img_id)
        except Exception as e:
            logger.error(f"[{self.account.address}] init_slide error: {e}")
            return False

    async def check(self, x, _id):
        try:
            json_data = {
                'id': _id,
                'bgImageWidth': 295,
                'bgImageHeight': 180,
                'startTime': 1709811268443,
                'endTime': 1709811275499,
                'trackPointList': [
                    {
                        'x': 0,
                        'y': 0,
                        't': 5449,
                    },
                    {
                        'x': 1,
                        'y': 0,
                        't': 5537,
                    },
                    {
                        'x': 3,
                        'y': 0,
                        't': 5549,
                    },
                    {
                        'x': 6,
                        'y': -1,
                        't': 5561,
                    },
                    {
                        'x': 11,
                        'y': -2,
                        't': 5573,
                    },
                    {
                        'x': 17,
                        'y': -2,
                        't': 5604,
                    },
                    {
                        'x': 26,
                        'y': -2,
                        't': 5615,
                    },
                    {
                        'x': 73,
                        'y': -4,
                        't': 5627,
                    },
                    {
                        'x': 87,
                        'y': -4,
                        't': 5637,
                    },
                    {
                        'x': 97,
                        'y': -4,
                        't': 5648,
                    },
                    {
                        'x': 110,
                        'y': -4,
                        't': 5659,
                    },
                    {
                        'x': 124,
                        'y': -5,
                        't': 5671,
                    },
                    {
                        'x': 135,
                        'y': -5,
                        't': 5684,
                    },
                    {
                        'x': 145,
                        'y': -5,
                        't': 5693,
                    },
                    {
                        'x': 154,
                        'y': -5,
                        't': 5705,
                    },
                    {
                        'x': 161,
                        'y': -5,
                        't': 5715,
                    },
                    {
                        'x': 166,
                        'y': -5,
                        't': 5727,
                    },
                    {
                        'x': 168,
                        'y': -5,
                        't': 5738,
                    },
                    {
                        'x': 170,
                        'y': -4,
                        't': 5750,
                    },
                    {
                        'x': 170,
                        'y': -4,
                        't': 5763,
                    },
                    {
                        'x': 171,
                        'y': -4,
                        't': 5772,
                    },
                    {
                        'x': 171,
                        'y': -4,
                        't': 5786,
                    },
                    {
                        'x': 171,
                        'y': -4,
                        't': 5797,
                    },
                    {
                        'x': 173,
                        'y': -4,
                        't': 5808,
                    },
                    {
                        'x': 173,
                        'y': -4,
                        't': 5818,
                    },
                    {
                        'x': 176,
                        'y': -4,
                        't': 5829,
                    },
                    {
                        'x': 176,
                        'y': -4,
                        't': 5842,
                    },
                    {
                        'x': 177,
                        'y': -4,
                        't': 5851,
                    },
                    {
                        'x': 177,
                        'y': -4,
                        't': 5978,
                    },
                    {
                        'x': 177,
                        'y': -4,
                        't': 5990,
                    },
                    {
                        'x': 177,
                        'y': -4,
                        't': 6002,
                    },
                    {
                        'x': 177,
                        'y': -4,
                        't': 6014,
                    },
                    {
                        'x': 178,
                        'y': -4,
                        't': 6021,
                    },
                    {
                        'x': 178,
                        'y': -4,
                        't': 6033,
                    },
                    {
                        'x': 179,
                        'y': -4,
                        't': 6045,
                    },
                    {
                        'x': 180,
                        'y': -4,
                        't': 6054,
                    },
                    {
                        'x': 180,
                        'y': -4,
                        't': 6065,
                    },
                    {
                        'x': 181,
                        'y': -4,
                        't': 6077,
                    },
                    {
                        'x': 181,
                        'y': -4,
                        't': 6100,
                    },
                    {
                        'x': 181,
                        'y': -4,
                        't': 6110,
                    },
                    {
                        'x': 182,
                        'y': -4,
                        't': 6138,
                    },
                    {
                        'x': 182,
                        'y': -4,
                        't': 6145,
                    },
                    {
                        'x': 182,
                        'y': -4,
                        't': 6157,
                    },
                    {
                        'x': 183,
                        'y': -4,
                        't': 6169,
                    },
                    {
                        'x': 184,
                        'y': -4,
                        't': 6178,
                    },
                    {
                        'x': 184,
                        'y': -4,
                        't': 6191,
                    },
                    {
                        'x': 184,
                        'y': -4,
                        't': 6201,
                    },
                    {
                        'x': 185,
                        'y': -4,
                        't': 6222,
                    },
                    {
                        'x': 185,
                        'y': -4,
                        't': 6257,
                    },
                    {
                        'x': 185,
                        'y': -4,
                        't': 6267,
                    },
                    {
                        'x': 186,
                        'y': -4,
                        't': 6280,
                    },
                    {
                        'x': 186,
                        'y': -4,
                        't': 6290,
                    },
                    {
                        'x': 186,
                        'y': -4,
                        't': 6304,
                    },
                    {
                        'x': 186,
                        'y': -4,
                        't': 6336,
                    },
                    {
                        'x': 187,
                        'y': -4,
                        't': 6336,
                    },
                    {
                        'x': 187,
                        'y': -4,
                        't': 6368,
                    },
                    {
                        'x': 187,
                        'y': -4,
                        't': 6370,
                    },
                    {
                        'x': 188,
                        'y': -4,
                        't': 6380,
                    },
                    {
                        'x': 188,
                        'y': -4,
                        't': 6393,
                    },
                    {
                        'x': 188,
                        'y': -4,
                        't': 6405,
                    },
                    {
                        'x': 189,
                        'y': -4,
                        't': 6415,
                    },
                    {
                        'x': 189,
                        'y': -4,
                        't': 6426,
                    },
                    {
                        'x': 189,
                        'y': -4,
                        't': 6436,
                    },
                    {
                        'x': 190,
                        'y': -4,
                        't': 6448,
                    },
                    {
                        'x': 190,
                        'y': -4,
                        't': 6460,
                    },
                    {
                        'x': 190,
                        'y': -4,
                        't': 6471,
                    },
                    {
                        'x': 191,
                        'y': -4,
                        't': 6483,
                    },
                    {
                        'x': 191,
                        'y': -4,
                        't': 6505,
                    },
                    {
                        'x': 191,
                        'y': -4,
                        't': 6519,
                    },
                    {
                        'x': 192,
                        'y': -4,
                        't': 6527,
                    },
                    {
                        'x': 192,
                        'y': -4,
                        't': 6539,
                    },
                    {
                        'x': 192,
                        'y': -4,
                        't': 6550,
                    },
                    {
                        'x': 193,
                        'y': -4,
                        't': 6560,
                    },
                    {
                        'x': 193,
                        'y': -4,
                        't': 6594,
                    },
                    {
                        'x': 193,
                        'y': -4,
                        't': 6652,
                    },
                    {
                        'x': 193,
                        'y': -4,
                        't': 6696,
                    },
                    {
                        'x': 193,
                        'y': -4,
                        't': 6832,
                    },
                    {
                        'x': 194,
                        'y': -4,
                        't': 6865,
                    },
                    {
                        'x': x,
                        'y': -4,
                        't': 7056,
                    },
                ],
            }
            res = await self.http.post('https://game.metalist.io/api/user/checkCaptcha', json=json_data)
            if res.json()['code'] == '000000':
                return True
            logger.error(f"[{self.account.address}] check error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] check error: {e}")
            return False

    async def signatureContent(self):
        try:
            json_data = {"address": self.account.address.lower()}
            res = await self.http.post("https://game.metalist.io/api/user/signatureContent", json=json_data)
            if res.json()['code'] == '000000':
                return res.json()['data']
            logger.error(f"[{self.account.address}] signatureContent error: {res.json()}")
            return None
        except Exception as e:
            logger.error(f"[{self.account.address}] signatureContent error: {e}")
            return None

    async def login(self):
        try:
            signatureContent = await self.signatureContent()
            if signatureContent is None:
                return False
            signature = self.account.sign_message(encode_defunct(text=signatureContent))
            json_data = {
                "channel": "wallet",
                "clientAppId": "13x67d4icclyebny",
                "code": signature.signature.hex(),
                "client": 1,
                "extra": self.account.address.lower(),
                "userNumber": "",
                "redirectUri": "",
                "captchaId": self.img_id,
            }
            res = await self.http.post("https://game.metalist.io/api/user/login", json=json_data)
            if res.json()['code'] == '000000':
                loginSymbol = res.json()['data']['loginSymbol']
                nickName = res.json()['data']['nickName']
                n = res.json()['data']['n']
                return await self.getTokenId(loginSymbol, nickName, n, "snk5i6")
            logger.error(f"[{self.account.address}] login error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] login error: {e}")
            return False

    async def getTokenId(self, loginSymbol, nickName, n, inviteCode):
        try:
            json_data = {
                "type": 1,
                "loginInfo": '{\"type\":\"Email\",\"success\":true,\"n\":\"' + n + '\",\"nickName\":\"' + nickName + '\",\"loginSymbol\":\"' + loginSymbol + '\",\"bizType\":\"login\",\"hasActivationCode\":false}',
                "inviteCode": inviteCode
            }
            res = await self.http.post("https://cardsahoy.metalist.io/commonApi/user/login", json=json_data)
            if res.json()['code'] == '000000':
                self.tokenid = res.json()['data']
                self.http.headers['Tokenid'] = self.tokenid
                return True
            logger.error(f"[{self.account.address}] getTokenId error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] getTokenId error: {e}")
            return False

    async def getInfo(self):
        try:
            res = await self.http.post("https://cardsahoy.metalist.io/commonApi/user/queryCurrentUser")
            if res.json()['code'] == '000000':
                if res.json()['data']['twitter'] is None:
                    return await self.bindTwitter()
                return True
            logger.error(f"[{self.account.address}] getInfo error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] getInfo error: {e}")
            return False

    async def bindTwitter(self):
        try:
            code_challenge = ''.join(random.choice(string.digits + string.ascii_letters) for _ in range(10))
            twitter = Twitter(self.auth_token, code_challenge, self.proxies)
            if not await twitter.twitter_authorize():
                return False
            json_data = {
                "code": twitter.auth_code,
                "codeVerifier": code_challenge,
                "callback": "https://cardsahoy.metalist.io/airdrop-h5"
            }
            res = await self.http.post("https://cardsahoy.metalist.io/commonApi/user/bindTwitter", json=json_data)
            if res.json()['code'] == '000000':
                return True
            logger.error(f"[{self.account.address}] bindTwitter error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] bindTwitter error: {e}")
            return False

    async def task(self):
        try:
            task_id = [41, 42, 43, 44]
            for i in task_id:
                await self.verify(i)
            rewards = ''
            for _ in range(4):
                reward = await self.scratchLotto()
                rewards += reward + '|'
            rewards = rewards[:-1]
            logger.success(f"[{self.account.address}] 刮奖获得{rewards}")
            with open('刮奖成功.txt', 'a', encoding='utf-8') as file:
                file.write(f'{self.account.address}----{self.private_key}----{self.tokenid}----{rewards}\n')
                file.flush()
            return True
        except Exception as e:
            logger.error(f"[{self.account.address}] task error: {e}")
            return False

    async def verify(self, task_id):
        try:
            json_data = {"taskId": task_id}
            res = await self.http.post("https://cardsahoy.metalist.io/ahoyApi/pubicTestTask/verify", json=json_data)
            if res.json()['code'] == '000000':
                return await self.claim(task_id)
            logger.error(f"[{self.account.address}] verify error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] verify error: {e}")
            return False

    async def claim(self, task_id):
        try:
            json_data = {"taskId": task_id}
            res = await self.http.post("https://cardsahoy.metalist.io/ahoyApi/pubicTestTask/claim", json=json_data)
            if res.json()['code'] == '000000':
                return True
            logger.error(f"[{self.account.address}] claim error: {res.json()}")
            return False
        except Exception as e:
            logger.error(f"[{self.account.address}] claim error: {e}")
            return False

    async def scratchLotto(self):
        try:
            res = await self.http.post("https://cardsahoy.metalist.io/ahoyApi/pubicTestActivity/scratchLotto", json={"cardType": "common"})
            if res.json()['code'] == '000000':
                rewardName = res.json()['data']['rewardName']
                rewardAmount = res.json()['data']['rewardAmount']
                # logger.success(f"[{self.account.address}] 刮奖获得{rewardName}x{rewardAmount}")
                return f"{rewardName}x{rewardAmount}"
            logger.error(f"[{self.account.address}] scratchLotto error: {res.json()}")
            return None
        except Exception as e:
            logger.error(f"[{self.account.address}] scratchLotto error: {e}")
            return None


async def lotto(semaphore, account, nstproxy_Channel, nstproxy_Password):
    async with semaphore:
        accountList = account.strip().split('----')
        M = metalist(accountList[1], accountList[2], nstproxy_Channel, nstproxy_Password)
        if await M.captcha() and await M.login() and await M.getInfo() and await M.task():
            logger.success(f"{M.account.address} 任务完成")


async def task(accounts, nstproxy_Channel, nstproxy_Password):
    semaphore = asyncio.Semaphore(5)
    tasks = [lotto(semaphore, account, nstproxy_Channel, nstproxy_Password) for account in accounts]
    await asyncio.gather(*tasks)


def main(accounts, nstproxy_Channel, nstproxy_Password):
    asyncio.run(task(accounts, nstproxy_Channel, nstproxy_Password))


def run(account_path, nstproxy_Channel, nstproxy_Password):
    processes = os.cpu_count()
    try:
        with open('刮奖成功.txt', 'r', encoding='utf-8') as f:
            checked = set(line.strip().split('----')[0] for line in f)
    except FileNotFoundError:
        checked = set()
    with open(account_path, 'r', encoding='utf-8') as f:
        account_list = [line for line in f.readlines() if line.strip().split('----')[0] not in checked]

    logger.info(f'剩余任务数量：{len(account_list)}')
    if len(account_list) == 0:
        logger.error('账号已全部完成')
        return

    k, m = divmod(len(account_list), processes)
    account_price = [account_list[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(processes)]

    with Pool(processes=processes) as pool:
        for accounts in account_price:
            pool.apply_async(main, args=(accounts, nstproxy_Channel, nstproxy_Password))
        pool.close()
        pool.join()


if __name__ == '__main__':
    hdd = ''' __    __   _______   _______        ______ .___  ___. 
|  |  |  | |       \ |       \      /      ||   \/   | 
|  |__|  | |  .--.  ||  .--.  |    |  ,----'|  \  /  | 
|   __   | |  |  |  ||  |  |  |    |  |     |  |\/|  | 
|  |  |  | |  '--'  ||  '--'  | __ |  `----.|  |  |  | 
|__|  |__| |_______/ |_______/ (__) \______||__|  |__| 
                    hdd.cm推特低至2毛                        '''
    print(hdd)
    print('代理：https://app.nstproxy.com/register?i=7JunWz')
    _nstproxy_Channel = input('请输入nstproxy_频道:').strip()
    _nstproxy_Password = input('请输入nstproxy_密码:').strip()
    _account_path = input('请拖入你的文件或输入完整路径(地址----私钥----推特auth_token):').strip()
    for _ in range(10):
        run(_account_path, _nstproxy_Channel, _nstproxy_Password)
