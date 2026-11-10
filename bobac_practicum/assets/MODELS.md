# 人脸检测模型来源

模型和网络结构来自 OpenCV 官方仓库：

- https://github.com/opencv/opencv/tree/3.3.1/samples/dnn/face_detector
- https://github.com/opencv/opencv_3rdparty/tree/dnn_samples_face_detector_20170830
- deploy.prototxt SHA256: d4be66cc104fef5deb5aac6a8adc30ff09c72997cffb2bf1453e7bc610a0fd3b
- res10_300x300_ssd_iter_140000.caffemodel SHA256: 2a56a11a57a4a295956b0660b4a3d76bbdca2206c4961cea8efe7d95c7cb2f2d

人脸框检测使用 SSD ResNet-10；身份匹配使用 OpenFace 128 维特征，LBPH 作为后备。不把检测置信度或特征相似度当作身份准确率。
机器人 ROS OpenCV 3.3.1-dev 的 DNN forward 在实机报错，因此使用独立 Python 2.7 子进程及项目私有 OpenCV 3.4.2 依赖，不覆盖 ROS 的 cv2。
依赖来源为 PyPI opencv-python 3.4.2.17，wheel 自带许可文件，保留在机器人私有依赖目录。该 wheel 不打包进源码；重装步骤见 README。

OpenFace 模型来自 Carnegie Mellon University 的官方存储：

- https://storage.cmusatyalab.org/openface-models/nn4.small2.v1.t7
- 官方下载与校验脚本：https://github.com/cmusatyalab/openface/blob/master/models/get-models.sh
- 官方 MD5：c95bfd8cc1adf05210e979ff623013b6
- SHA256：9b72d54aeb24a64a8135dca8e792f7cc675c99a884a6940350a6cedcf7b7ba08
- Apache 2.0，许可文件 `OpenFace-LICENSE.txt` 随附。

为复用已同意采集的灰度样本，训练模板与实时画面统一使用相同的灰度、直方图均衡化、96x96 输入。当前未实现模型原始方案的关键点仿射对齐，不援引公开数据集成绩作为本项目的识别率；现场独立验收仍须另做。
