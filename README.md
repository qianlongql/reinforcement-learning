# 利用强化学习训练 Agent 玩 Atari 游戏
## 复现论文
### 预处理
Atari游戏返回的画面大小为210x160x3的彩色图，首先将其转化为灰度图。
图片顶端为计分栏应裁掉以免造成干扰，生成160x160的样本图。
根据论文将图片resize为84x84，同时将四帧连续的图片组成一个样本训练神经网络  
### 神经网络结构
输入：84x84x4的图片  
第一层卷积：16个8x8卷积核，步长为4  
第二层卷积：32个4x4卷积核，步长为2  
第三层全连接：输入32x9x9，输出256  
第四层全连接：输入256，输出6对应6个动作  
（我们考虑在卷积与全连接之间加一层最大池化层以增强特征，但由于训练轮数限制暂不能比较出两者的差异）  
### 记忆池
通过队列或数组存储每一步的[state, action, reward, next_state, done]
### 行为决策：ϵ-greedy 策略
ϵ-greedy 策略兼具探索与利用的功能，在已知与未知之间进行了平衡  
通过引入随机行为，增强了对游戏的探索，同时能产生更多有用的样本   
样本的随机化破坏了该相关性，从而减少了更新的方差   
并且随着训练的进行逐渐减少随机行为，使最终的模型能利用已有的训练记忆更好地进行决策
### 神经网络优化
根据论文的算法，运用贝尔曼公式  
Q(s,a) ← Q(s,a)+α[r+γmaxa'Q(s',a')−Q(s,a)]   
损失函数为  
L(θ)=E[(TargetQ−Q(s,a;θ))^2]  
通过对loss的梯度下降调整神经网络参数  
同时为了降低相关性，使用了两个初始相同的神经网络target-netwoek与 eval-network  
eval-network一直训练更新，而target-network则周期性地与eval-network同步  
### 代码实现
我们独立地用tensorflow编写了一段完整代码，实现了对Space-invaders和Breakout游戏的训练。  
同时我们查阅了github上相关项目代码，在现有代码的基础上，使用pytorch进行了一定的改进，如消除图片闪烁，并尝试将四帧连续图片改为三帧，同时增大神经网络的结点数，提高记忆池容量，并在卷积与全连接层之间加入了最大池化层。但由于训练轮数有限，暂不能说明改进情况。
### 训练结果
通过1000轮的训练，模型的得分大致稳定在200左右，效果并不好，训练到最后依然不会躲避子弹。
![image](https://github.com/qianlongql/reinforcement-learning/blob/master/%E7%BB%93%E6%9E%9C/training%20reward.png)  
![image](https://github.com/qianlongql/reinforcement-learning/blob/master/%E7%BB%93%E6%9E%9C/training%20result.png)  
模型在训练过程中会出现异常现象，如停止不动，不发射子弹等






