"""
Created on Apr 13, 2017

@author: sgoldsmith

Copyright (c) Steven P. Goldsmith

All rights reserved.
"""

import logging, sys, traceback, time, datetime, importlib, threading, config, motiondet, observer

class videoloop(observer.observer):
    """Main class used to acquire and process frames.
    
    The idea here is to keep things moving as fast as possible. Anything that
    would slow down frame processing should be off loaded to a thread or
    background process.
    
    """

    def __init__(self, fileName):
        # Get app configuration
        self.appConfig = config.config(fileName)        
        # Set up logger
        self.logger = logging.getLogger("videoloop")
        self.logger.setLevel(self.appConfig.loggingLevel)
        formatter = logging.Formatter(self.appConfig.loggingFormatter)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.info("Configuring from file: %s" % fileName)
        self.logger.info("Logging level: %s" % self.appConfig.loggingLevel)
        self.logger.debug("Logging formatter: %s" % self.appConfig.loggingFormatter)
        # Get frame grabber plugin
        self.logger.info("Loading frame grabber plugin: %s" % self.appConfig.framePlugin)
        self.framePluginInstance = self.getPlugin(moduleName=self.appConfig.framePlugin, url=self.appConfig.url)
        # If codeferm.videocapture is selected then set VideoCapture properties
        if self.appConfig.framePlugin == "codeferm.videocapture":
            self.framePluginInstance.setProperties(self.appConfig.videoCaptureProperties)
        self.logger.debug("Height: %d, width: %d, fps: %d" % (self.framePluginInstance.frameHeight, self.framePluginInstance.frameWidth, self.framePluginInstance.fps))
        self.frameOk = True

    def getPlugin(self, moduleName, **kwargs):
        """Dynamically load module"""
        # If package name passed then parse out class name
        moduleSplit = moduleName.split(".")
        if len(moduleSplit) > 1:
            moduleClass = moduleSplit[1]
        else:
            moduleClass = moduleName
        module = importlib.import_module(moduleName)
        moduleClass = getattr(module, moduleClass)
        return moduleClass(**kwargs)

    def readFrames(self, frameBuf):
        """Read frames and append to buffer"""
        while(self.frameOk):
            now = datetime.datetime.now()
            frame = self.framePluginInstance.getFrame()
            self.frameOk = len(frame) > 0
            if self.frameOk:
                # Make sure we do not run out of memory
                if len(frameBuf) > self.appConfig.frameBufMax:
                    self.logger.error("Frame buffer exceeded: %d" % self.appConfig.frameBufMax)
                    self.frameOk = False
                else:
                    # Add new image to end of list
                    frameBuf.append((self.framePluginInstance.decodeFrame(frame), now))
        self.logger.info("Exiting readFrames thread")
        
    def observeEvent(self, **kwargs):
        "Handle events"
        if kwargs["event"] == motiondet.motiondet.motionStart:
            self.logger.debug("Motion start: %4.2f%%" % kwargs["motionPercent"])
        elif kwargs["event"] == motiondet.motiondet.motionStop:
            self.logger.debug("Motion stop: %4.2f%%" % kwargs["motionPercent"])

    def run(self):
        """Video processing loop"""
        frameWidth = self.framePluginInstance.frameWidth
        frameHeight = self.framePluginInstance.frameHeight
        # See if plug in has FPS set
        if self.framePluginInstance.fps == 0:
            fps = self.appConfig.fps
        elif self.appConfig.fps == 0:
            fps = self.framePluginInstance.fps
        else:
            fps = self.appConfig.fps
        if frameWidth > 0 and frameHeight > 0:
            # Analyze only ~3 FPS which works well with this type of detection
            frameToCheck = int(fps / 4)
            # 0 means check every frame
            if frameToCheck < 1:
                frameToCheck = 0
            skipCount = 0
            elapsedFrames = 0    
            # Frame buffer
            frameBuf = []
            # History buffer to capture just before motion
            historyBuf = []
            # Kick off readFrames thread
            thread = threading.Thread(target=self.readFrames, args=(frameBuf,))
            thread.start()
            # Wait until buffer is full
            while(self.frameOk and len(frameBuf) < fps):
                # 1/4 of FPS sleep
                time.sleep(1.0 / (fps * 4))
            # Motion detection object
            motion = motiondet.motiondet(self.appConfig, frameBuf[0][0], self.logger)
            # Observe motion events
            motion.addObserver(self)
            start = time.time()
            # Loop as long as there are frames in the buffer
            while(len(frameBuf) > 0):
                # Calc FPS    
                elapsedFrames += 1
                curTime = time.time()
                elapse = curTime - start
                # Log FPS
                if elapse >= self.appConfig.fpsInterval:
                    start = curTime
                    self.logger.debug("%3.1f FPS, frame buffer size: %d" % (elapsedFrames / elapse, len(frameBuf)))
                    elapsedFrames = 0                
                # Wait until frame buffer is full
                while(self.frameOk and len(frameBuf) < fps):
                    # 1/4 of FPS sleep
                    time.sleep(1.0 / (fps * 4))
                # Get oldest frame
                frame = frameBuf[0][0]
                # Used for timestamp in frame buffer and filename
                now = frameBuf[0][1]
                # Buffer oldest frame
                historyBuf.append(frameBuf[0])
                # Toss oldest history frame
                if len(historyBuf) > fps:
                    historyBuf.pop(0)
                # Toss oldest frame
                frameBuf.pop(0)
                # Skip frames until skip count <= 0
                if skipCount <= 0:
                    skipCount = frameToCheck
                    resizeImg, grayImg, bwImg, motionPercent, movementLocationsFiltered = motion.detect(frame)
                else:
                    skipCount -= 1
                
if __name__ == "__main__":
    try:
        # sys.argv[1] is configuration file or default is used
        if len(sys.argv) < 2:
            fileName = "../config/test.ini"
        else:
            fileName = sys.argv[1]
        videoLoop = videoloop(fileName)
        videoLoop.run()
    except:
        # Add timestamp to errors
        sys.stderr.write("%s " % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f"))
        traceback.print_exc(file=sys.stderr)
    # Do cleanup
    if videoLoop:
        videoLoop.framePluginInstance.close()
