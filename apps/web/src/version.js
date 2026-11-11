// 网页显示的版本号只有一个来源：package.json（和 speclock_config.__version__ 保持一致）
import pkg from '../package.json'

export const APP_VERSION = pkg.version
